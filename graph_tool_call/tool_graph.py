"""ToolGraph — main public API facade."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema, normalize_tool, parse_tool
from graph_tool_call.net import fetch_url_text
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import RelationType
from graph_tool_call.retrieval.engine import RetrievalEngine, RetrievalResult, SearchMode
from graph_tool_call.serialization import load_graph, save_graph


def _encode_spec_url(base: str, raw_url: str) -> str:
    """Convert a raw spec URL (possibly with spaces/unicode) to an absolute, encoded URL."""
    absolute = urljoin(base + "/", raw_url)
    # Re-encode the path portion to handle spaces and non-ASCII characters
    # Split at the scheme+host boundary, encode only the path
    if "://" in absolute:
        scheme_host, _, path = absolute.partition("://")
        host, _, path_part = path.partition("/")
        encoded_path = quote("/" + path_part, safe="/:@!$&'()*+,;=-._~")
        return f"{scheme_host}://{host}{encoded_path}"
    return absolute


def _discover_spec_urls(
    url: str,
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> list[str]:
    """Discover OpenAPI spec URLs from a Swagger UI or direct spec URL.

    If the URL contains ``/swagger-ui``, attempts to find the swagger-config
    endpoint and extract spec URLs from it. Otherwise returns the URL as-is.

    Discovery order:
    1. Common swagger-config endpoints (SpringDoc v1/v2)
    2. Parse ``swagger-initializer.js`` to extract ``configUrl``
    3. Fallback to ``{base}/v3/api-docs``
    """
    swagger_ui_marker = "/swagger-ui"
    if swagger_ui_marker not in url:
        return [url]

    base = url[: url.index(swagger_ui_marker)]
    ui_base = url[: url.index(swagger_ui_marker)] + "/swagger-ui"

    # Step 1: Try common swagger-config endpoints
    config_urls_to_try = [
        f"{base}/swagger-config",
        f"{base}/v3/api-docs/swagger-config",
        f"{base}/api-docs/swagger-config",
    ]
    for config_url in config_urls_to_try:
        result = _try_swagger_config(
            config_url,
            base,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        if result:
            return result

    # Step 2: Parse swagger-initializer.js to find configUrl
    init_js_url = f"{ui_base}/swagger-initializer.js"
    try:
        js_text = fetch_url_text(
            init_js_url,
            timeout=10,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
            allowed_content_types=("application/javascript", "text/javascript", "text/plain"),
        )
        # Extract configUrl from JS: "configUrl" : "/api/bo/api-docs/swagger-config"
        match = re.search(r'"configUrl"\s*:\s*"([^"]+)"', js_text)
        if match:
            config_path = match.group(1)
            # Build absolute config URL
            if config_path.startswith("/"):
                # Absolute path — combine with scheme+host
                from urllib.parse import urlparse

                parsed = urlparse(url)
                config_url = f"{parsed.scheme}://{parsed.netloc}{config_path}"
            else:
                config_url = urljoin(base + "/", config_path)
            result = _try_swagger_config(
                config_url,
                base,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )
            if result:
                return result
    except Exception:  # noqa: BLE001
        pass

    # Step 3: Fallback
    return [f"{base}/v3/api-docs"]


def _try_swagger_config(
    config_url: str,
    base: str,
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> list[str] | None:
    """Try fetching a swagger-config URL and extract spec URLs."""
    try:
        text = fetch_url_text(
            config_url,
            timeout=10,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        config = json.loads(text)
        urls = config.get("urls", [])
        if urls:
            return [_encode_spec_url(base, u["url"]) for u in urls if "url" in u]
    except Exception:  # noqa: BLE001
        pass
    return None


class ToolGraph:
    """High-level API for graph-structured tool management and retrieval.

    Usage::

        tg = ToolGraph()
        tg.add_tools(openai_tools_list)
        tg.add_relation("read_file", "write_file", "complementary")
        tools = tg.retrieve("read and write files", top_k=5)
    """

    def __init__(self, graph: GraphEngine | None = None) -> None:
        self._graph: GraphEngine = graph if graph is not None else NetworkXGraph()
        self._builder = OntologyBuilder(self._graph)
        self._tools: dict[str, ToolSchema] = {}
        self._retrieval: RetrievalEngine | None = None

    @property
    def graph(self) -> GraphEngine:
        return self._graph

    @property
    def tools(self) -> dict[str, ToolSchema]:
        return dict(self._tools)

    @property
    def builder(self) -> OntologyBuilder:
        return self._builder

    # --- tool registration ---

    def add_tool(self, tool: Any) -> ToolSchema:
        """Add a single tool (auto-detects format)."""
        schema = parse_tool(tool)
        normalize_tool(schema)
        self._tools[schema.name] = schema
        self._builder.add_tool(schema)
        self._invalidate_retrieval()
        return schema

    def add_tools(
        self,
        tools: list[Any],
        *,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
    ) -> list[ToolSchema]:
        """Add multiple tools (auto-detects format for each).

        Parameters
        ----------
        detect_dependencies:
            If True (default), run automatic dependency detection on the batch.
        min_confidence:
            Minimum confidence threshold for detected relations.
        """
        schemas = [self.add_tool(t) for t in tools]

        # Batch category assignment
        categories_seen: set[str] = set()
        for schema in schemas:
            if schema.domain:
                if schema.domain not in categories_seen:
                    if not self._graph.has_node(schema.domain):
                        self._builder.add_category(schema.domain)
                    categories_seen.add(schema.domain)
                self._builder.assign_category(schema.name, schema.domain)

        # Batch dependency detection
        if detect_dependencies and len(schemas) >= 2:
            from graph_tool_call.analyze.dependency import detect_dependencies as _detect

            relations = _detect(schemas, min_confidence=min_confidence)
            for rel in relations:
                self._builder.add_relation(rel.source, rel.target, rel.relation_type)

        if schemas:
            self._invalidate_retrieval()
        return schemas

    # --- ingest ---

    def ingest_openapi(
        self,
        source: dict[str, Any] | str,
        *,
        required_only: bool = False,
        skip_deprecated: bool = True,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
        allow_private_hosts: bool = False,
        max_response_bytes: int = 5_000_000,
    ) -> list[ToolSchema]:
        """Ingest an OpenAPI/Swagger spec, register tools, and auto-detect relations.

        Parameters
        ----------
        source:
            A raw spec dict, a file path (JSON/YAML), or a URL (http/https).
        required_only:
            If True, only include required parameters.
        skip_deprecated:
            If True (default), skip deprecated operations.
        detect_dependencies:
            If True (default), run automatic dependency detection.
        min_confidence:
            Minimum confidence threshold for detected relations.

        Returns
        -------
        list[ToolSchema]
            The ingested tool schemas.
        """
        from graph_tool_call.ingest.openapi import ingest_openapi

        tools, spec = ingest_openapi(
            source,
            required_only=required_only,
            skip_deprecated=skip_deprecated,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )

        # Register tools
        for tool in tools:
            self._tools[tool.name] = tool
            self._builder.add_tool(tool)

        # Auto-categorize: use tool.domain (set by ingest) as category
        categories_seen: set[str] = set()
        for tool in tools:
            if tool.domain:
                if tool.domain not in categories_seen:
                    if not self._graph.has_node(tool.domain):
                        self._builder.add_category(tool.domain)
                    categories_seen.add(tool.domain)
                self._builder.assign_category(tool.name, tool.domain)

        # Auto-detect dependencies
        if detect_dependencies:
            from graph_tool_call.analyze.dependency import detect_dependencies as _detect

            relations = _detect(tools, spec=spec.raw, min_confidence=min_confidence)
            for rel in relations:
                self._builder.add_relation(rel.source, rel.target, rel.relation_type)

        self._invalidate_retrieval()
        return tools

    def ingest_mcp_tools(
        self,
        tools: list[dict[str, Any]],
        *,
        server_name: str | None = None,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
    ) -> list[ToolSchema]:
        """Ingest MCP tool list, register tools, and auto-detect relations.

        Parameters
        ----------
        tools:
            List of MCP tool dicts (``name``, ``inputSchema``, ``annotations``).
        server_name:
            Optional MCP server name for tagging.
        detect_dependencies:
            If True (default), run automatic dependency detection.
        min_confidence:
            Minimum confidence threshold for detected relations.

        Returns
        -------
        list[ToolSchema]
            The ingested tool schemas.
        """
        from graph_tool_call.ingest.mcp import ingest_mcp_tools

        schemas = ingest_mcp_tools(tools, server_name=server_name)

        # Register tools and assign categories
        categories_seen: set[str] = set()
        for schema in schemas:
            self._tools[schema.name] = schema
            self._builder.add_tool(schema)
            if schema.domain:
                if schema.domain not in categories_seen:
                    if not self._graph.has_node(schema.domain):
                        self._builder.add_category(schema.domain)
                    categories_seen.add(schema.domain)
                self._builder.assign_category(schema.name, schema.domain)

        if detect_dependencies and len(schemas) >= 2:
            from graph_tool_call.analyze.dependency import detect_dependencies as _detect

            relations = _detect(schemas, min_confidence=min_confidence)
            for rel in relations:
                self._builder.add_relation(rel.source, rel.target, rel.relation_type)

        self._invalidate_retrieval()
        return schemas

    def ingest_mcp_server(
        self,
        server_url: str,
        *,
        server_name: str | None = None,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
        allow_private_hosts: bool = False,
        max_response_bytes: int = 5_000_000,
        timeout: int = 30,
    ) -> list[ToolSchema]:
        """Fetch tools from an MCP server endpoint and ingest them.

        The endpoint is expected to support HTTP JSON-RPC ``tools/list``.
        """
        from graph_tool_call.ingest.mcp import fetch_mcp_tools

        remote_tools, discovered_name = fetch_mcp_tools(
            server_url,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
            timeout=timeout,
        )
        effective_name = server_name or discovered_name
        return self.ingest_mcp_tools(
            remote_tools,
            server_name=effective_name,
            detect_dependencies=detect_dependencies,
            min_confidence=min_confidence,
        )

    def ingest_functions(
        self,
        fns: Iterable[Callable[..., Any]],
        *,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
    ) -> list[ToolSchema]:
        """Ingest Python callables into the tool graph.

        Uses ``inspect.signature`` and type hints to extract parameters.

        Parameters
        ----------
        detect_dependencies:
            If True (default), run automatic dependency detection.
        min_confidence:
            Minimum confidence threshold for detected relations.

        Returns
        -------
        list[ToolSchema]
            The ingested tool schemas.
        """
        from graph_tool_call.ingest.functions import ingest_functions

        tools = ingest_functions(fns)

        # Register tools and assign categories
        categories_seen: set[str] = set()
        for tool in tools:
            self._tools[tool.name] = tool
            self._builder.add_tool(tool)
            if tool.domain:
                if tool.domain not in categories_seen:
                    if not self._graph.has_node(tool.domain):
                        self._builder.add_category(tool.domain)
                    categories_seen.add(tool.domain)
                self._builder.assign_category(tool.name, tool.domain)

        if detect_dependencies and len(tools) >= 2:
            from graph_tool_call.analyze.dependency import detect_dependencies as _detect

            relations = _detect(tools, min_confidence=min_confidence)
            for rel in relations:
                self._builder.add_relation(rel.source, rel.target, rel.relation_type)

        self._invalidate_retrieval()
        return tools

    def ingest_arazzo(
        self,
        source: Any,
        *,
        allow_private_hosts: bool = False,
        max_response_bytes: int = 5_000_000,
    ) -> list:
        """Ingest an Arazzo 1.0.0 workflow spec, adding PRECEDES relations.

        Only adds relations between tools already registered in the graph.

        Returns
        -------
        list[ArazzoRelation]
            The detected workflow relations.
        """
        from graph_tool_call.ingest.arazzo import ingest_arazzo

        relations = ingest_arazzo(
            source,
            registered_tools=set(self._tools.keys()),
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        for rel in relations:
            self._builder.add_relation(rel.source, rel.target, rel.relation_type)
        self._invalidate_retrieval()
        return relations

    # --- ontology ---

    def add_relation(
        self,
        source: str,
        target: str,
        relation: str | RelationType,
        weight: float = 1.0,
    ) -> None:
        """Add a relation between two tools."""
        self._builder.add_relation(source, target, relation, weight)
        self._invalidate_retrieval()

    def add_domain(self, domain: str, description: str = "") -> None:
        self._builder.add_domain(domain, description)

    def add_category(self, category: str, domain: str | None = None, description: str = "") -> None:
        self._builder.add_category(category, domain, description)

    def assign_category(self, tool_name: str, category: str) -> None:
        self._builder.assign_category(tool_name, category)
        self._invalidate_retrieval()

    def auto_organize(self, llm: Any = None) -> None:
        """Automatically organize tools using LLM (Phase 2).

        Parameters
        ----------
        llm:
            Any of: OntologyLLM instance, callable(str)->str, OpenAI client,
            or string shorthand like ``"ollama/qwen2.5:7b"``.
            If None, runs auto-mode only (tags/domain/embedding clustering).
        """
        from graph_tool_call.ontology.auto import auto_organize

        wrapped = None
        if llm is not None:
            from graph_tool_call.ontology.llm_provider import wrap_llm

            wrapped = wrap_llm(llm)
        auto_organize(self._builder, list(self._tools.values()), wrapped)
        self._invalidate_retrieval()  # BM25/embedding must rebuild from enriched ToolSchema

    def build_ontology(self, llm: Any = None, *, lint: bool = False, lint_level: int = 2) -> None:
        """Build a complete ontology from registered tools.

        Convenience method that runs auto-organization (and optionally LLM
        enhancement) on all currently registered tools.

        Parameters
        ----------
        llm:
            Any of: OntologyLLM instance, callable(str)->str, OpenAI client,
            or string shorthand like ``"ollama/qwen2.5:7b"``.
        lint:
            If True and tools were ingested from OpenAPI specs, re-lint is skipped
            (lint should be applied during ingest, not after).
        lint_level:
            Unused (reserved for future use). Lint is applied during ingest.
        """
        self.auto_organize(llm=llm)

    # --- deduplication ---

    def find_duplicates(self, *, threshold: float = 0.85) -> list:
        """Find duplicate tool pairs using the 5-stage pipeline.

        Returns a list of ``DuplicatePair`` objects.
        """
        from graph_tool_call.analyze.similarity import find_duplicates

        embedding_index = None
        if self._retrieval is not None:
            embedding_index = self._retrieval._embedding_index
        return find_duplicates(self._tools, threshold=threshold, embedding_index=embedding_index)

    def merge_duplicates(self, pairs: list, strategy: str = "keep_best") -> dict[str, str]:
        """Merge detected duplicates and update the graph.

        Returns a mapping of removed_name → kept_name.
        """
        from graph_tool_call.analyze.similarity import merge_duplicates as _merge

        merged = _merge(self._tools, pairs, strategy=strategy)

        # Apply merge: remove merged tools, add SIMILAR_TO edges for aliases
        from graph_tool_call.analyze.similarity import MergeStrategy

        strat = MergeStrategy(strategy) if isinstance(strategy, str) else strategy

        for removed, kept in merged.items():
            if strat == MergeStrategy.CREATE_ALIAS:
                self._builder.add_relation(removed, kept, RelationType.SIMILAR_TO)
            else:
                if removed in self._tools:
                    del self._tools[removed]
                if self._graph.has_node(removed):
                    self._graph.remove_node(removed)

        if merged:
            self._invalidate_retrieval()
        return merged

    # --- embedding ---

    def enable_embedding(self, embedding: Any = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        """Enable embedding-based hybrid search.

        Builds embeddings for all registered tools and attaches the index
        to the retrieval engine.  Weights are automatically rebalanced to
        graph=0.45, keyword=0.25, embedding=0.3.

        Parameters
        ----------
        embedding:
            Any of:

            - ``str`` shorthand: ``"openai/text-embedding-3-large"``,
              ``"ollama/nomic-embed-text"``,
              ``"sentence-transformers/all-MiniLM-L6-v2"``
            - ``callable(list[str]) -> list[list[float]]``
            - ``EmbeddingProvider`` instance
        """
        from graph_tool_call.retrieval.embedding import EmbeddingIndex, wrap_embedding

        provider = wrap_embedding(embedding)
        index = EmbeddingIndex(provider=provider)
        index.build_from_tools(self._tools)
        engine = self._get_retrieval_engine()
        engine.set_embedding_index(index)

    def enable_reranker(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        """Enable cross-encoder reranking for improved precision.

        Adds a second-stage reranker after wRRF fusion. The cross-encoder
        jointly encodes (query, tool_description) pairs for more precise scoring.
        """
        from graph_tool_call.retrieval.reranker import CrossEncoderReranker

        reranker = CrossEncoderReranker(model_name=model_name)
        engine = self._get_retrieval_engine()
        engine.set_reranker(reranker)

    def enable_diversity(self, lambda_: float = 0.7) -> None:
        """Enable MMR diversity reranking to reduce redundant results.

        Parameters
        ----------
        lambda_:
            Balance between relevance (1.0) and diversity (0.0). Default 0.7.
        """
        engine = self._get_retrieval_engine()
        engine.set_diversity(lambda_)

    def set_weights(
        self,
        *,
        keyword: float | None = None,
        graph: float | None = None,
        embedding: float | None = None,
        annotation: float | None = None,
    ) -> None:
        """Set wRRF fusion weights for retrieval.

        Default weights: keyword=0.3 (0.2 with embedding), graph=0.7 (0.5),
        embedding=0.0 (0.3 when enabled), annotation=0.2.

        Example::

            tg.enable_embedding("openai/text-embedding-3-large")
            tg.set_weights(embedding=0.5, keyword=0.1)  # boost embedding
        """
        engine = self._get_retrieval_engine()
        engine.set_weights(keyword=keyword, graph=graph, embedding=embedding, annotation=annotation)

    # --- retrieval ---

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[ToolSchema]:
        """Retrieve the most relevant tools for a query.

        Parameters
        ----------
        llm:
            Optional SearchLLM for ENHANCED/FULL modes.
            If None, ENHANCED/FULL fall back to BASIC.
        history:
            Optional list of previously called tool names for history-aware retrieval.
        """
        engine = self._get_retrieval_engine()
        return engine.retrieve(
            query,
            top_k=top_k,
            max_graph_depth=max_graph_depth,
            mode=mode,
            llm=llm,
            history=history,
        )

    def retrieve_with_scores(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
        llm: Any = None,
        history: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve tools with full score breakdown.

        Returns ``RetrievalResult`` objects with per-source scores
        (keyword, graph, embedding, annotation) and confidence level.

        Example::

            results = tg.retrieve_with_scores("delete user", top_k=3)
            for r in results:
                print(f"{r.tool.name}: {r.score:.4f} ({r.confidence})")
                print(f"  keyword={r.keyword_score:.2f} graph={r.graph_score:.2f}")
        """
        engine = self._get_retrieval_engine()
        return engine.retrieve_with_scores(
            query,
            top_k=top_k,
            max_graph_depth=max_graph_depth,
            mode=mode,
            llm=llm,
            history=history,
        )

    def _get_retrieval_engine(self) -> RetrievalEngine:
        if self._retrieval is None:
            self._retrieval = RetrievalEngine(self._graph, self._tools)
        return self._retrieval

    def _invalidate_retrieval(self) -> None:
        self._retrieval = None

    # --- from_url ---

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        required_only: bool = False,
        skip_deprecated: bool = True,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
        lint: bool = False,
        lint_level: int = 2,
        llm: Any = None,
        cache: str | Path | None = None,
        force: bool = False,
        progress: Callable[[str], None] | None = None,
        allow_private_hosts: bool = False,
        max_response_bytes: int = 5_000_000,
    ) -> ToolGraph:
        """Create a ToolGraph by fetching OpenAPI spec(s) from a URL.

        Supports:
        - Direct spec URLs (JSON/YAML)
        - Swagger UI URLs (auto-discovers specs via swagger-config)

        Parameters
        ----------
        lint:
            If True, run ai-api-lint auto-fix on the spec before ingest.
            Requires: ``pip install graph-tool-call[lint]``
        lint_level:
            Fixer level (1=safe only, 2=safe+inferred). Default 2.
        llm:
            Optional OntologyLLM instance for LLM-enhanced ontology construction.
            Runs auto_organize() with LLM after all specs are ingested.
        cache:
            Path to a JSON file for caching. If the file exists, the graph is
            loaded from it (skipping network fetch). If it doesn't exist, the
            graph is built normally and then saved to this path for reuse.
        force:
            If True, ignore existing cache and rebuild from source.
            The rebuilt graph is saved back to the cache path.
        progress:
            Optional callback for progress reporting. Called with a short
            status message at each major step. Example::

                tg = ToolGraph.from_url(url, progress=print)
        """
        _log = progress or (lambda _msg: None)

        if cache is not None:
            cache_path = Path(cache)
            if cache_path.exists() and not force:
                _log(f"Loading cached graph from {cache_path}")
                return cls.load(cache_path)
            if force and cache_path.exists():
                _log(f"Force rebuild — ignoring cache {cache_path}")

        from graph_tool_call.ingest.openapi import _load_spec

        _log(f"Discovering specs from {url}")
        spec_urls = _discover_spec_urls(
            url,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        _log(f"Found {len(spec_urls)} spec(s)")

        tg = cls()
        for i, spec_url in enumerate(spec_urls, 1):
            _log(f"Ingesting spec {i}/{len(spec_urls)}: {spec_url}")
            raw_spec = _load_spec(
                spec_url,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )

            if lint:
                from graph_tool_call.ingest.lint import lint_and_fix_spec

                _log(f"Linting spec {i}/{len(spec_urls)}")
                raw_spec, _ = lint_and_fix_spec(raw_spec, max_level=lint_level)

            tg.ingest_openapi(
                raw_spec,
                required_only=required_only,
                skip_deprecated=skip_deprecated,
                detect_dependencies=detect_dependencies,
                min_confidence=min_confidence,
                allow_private_hosts=allow_private_hosts,
                max_response_bytes=max_response_bytes,
            )

        if llm is not None:
            _log("Running LLM-enhanced ontology construction")
            tg.auto_organize(llm=llm)

        if cache is not None:
            build_metadata = {
                "source_url": url,
                "spec_urls": spec_urls,
                "build_options": {
                    "required_only": required_only,
                    "skip_deprecated": skip_deprecated,
                    "detect_dependencies": detect_dependencies,
                    "min_confidence": min_confidence,
                    "lint": lint,
                    "llm": llm is not None,
                    "allow_private_hosts": allow_private_hosts,
                    "max_response_bytes": max_response_bytes,
                },
            }
            _log(f"Saving graph to {cache_path}")
            tg.save(Path(cache), metadata=build_metadata)

        _log(f"Done — {len(tg._tools)} tools, {tg._graph.edge_count()} relations")
        return tg

    # --- serialization ---

    def save(self, path: str | Path, *, metadata: dict[str, Any] | None = None) -> None:
        """Save the tool graph to a JSON file.

        Parameters
        ----------
        metadata:
            Optional build metadata (source_urls, build_options, etc.).
        """
        retrieval_state: dict[str, Any] | None = None
        if self._retrieval is not None:
            retrieval_state = {
                "weights": {
                    "keyword": self._retrieval._keyword_weight,
                    "graph": self._retrieval._graph_weight,
                    "embedding": self._retrieval._embedding_weight,
                    "annotation": self._retrieval._annotation_weight,
                },
                "diversity_lambda": self._retrieval._diversity_lambda,
            }
            if self._retrieval._embedding_index is not None:
                retrieval_state["embedding_index"] = self._retrieval._embedding_index.to_dict()

        save_graph(
            self._graph,
            self._tools,
            path,
            metadata=metadata,
            retrieval_state=retrieval_state,
        )

    @classmethod
    def load(cls, path: str | Path) -> ToolGraph:
        """Load a tool graph from a JSON file."""
        graph, tools, metadata, retrieval_state = load_graph(path)
        tg = cls(graph=graph)
        tg._tools = tools
        tg._metadata = metadata
        tg._restore_retrieval_state(retrieval_state)
        return tg

    def _restore_retrieval_state(self, retrieval_state: dict[str, Any]) -> None:
        if not retrieval_state:
            return

        engine = self._get_retrieval_engine()
        weights = retrieval_state.get("weights", {})
        if isinstance(weights, dict):
            engine.set_weights(
                keyword=weights.get("keyword"),
                graph=weights.get("graph"),
                embedding=weights.get("embedding"),
                annotation=weights.get("annotation"),
            )

        diversity_lambda = retrieval_state.get("diversity_lambda")
        if isinstance(diversity_lambda, (int, float)):
            engine.set_diversity(float(diversity_lambda))

        embedding_state = retrieval_state.get("embedding_index")
        if isinstance(embedding_state, dict):
            from graph_tool_call.retrieval.embedding import EmbeddingIndex

            engine.set_embedding_index(EmbeddingIndex.from_dict(embedding_state))

    @property
    def metadata(self) -> dict[str, Any]:
        """Build metadata from the last save/load (source_urls, built_at, etc.)."""
        return getattr(self, "_metadata", {})

    # --- conflict detection ---

    def detect_conflicts(self, *, min_confidence: float = 0.6) -> list:
        """Detect conflicting tool pairs based on write operations and annotations.

        Returns a list of ``ConflictResult`` objects.
        """
        from graph_tool_call.analyze.conflict import detect_conflicts

        return detect_conflicts(list(self._tools.values()), min_confidence=min_confidence)

    def apply_conflicts(self, conflicts: list | None = None, *, min_confidence: float = 0.6) -> int:
        """Detect and apply CONFLICTS_WITH relations. Returns count of relations added."""
        from graph_tool_call.analyze.conflict import apply_conflicts, detect_conflicts

        if conflicts is None:
            conflicts = detect_conflicts(list(self._tools.values()), min_confidence=min_confidence)
        added = apply_conflicts(self, conflicts)
        if added:
            self._invalidate_retrieval()
        return added

    def analyze(
        self,
        *,
        duplicate_threshold: float = 0.85,
        conflict_min_confidence: float = 0.6,
    ) -> Any:
        """Build an operational analysis report for the current graph."""
        from graph_tool_call.analyze.report import analyze_graph

        duplicates = self.find_duplicates(threshold=duplicate_threshold)
        conflicts = self.detect_conflicts(min_confidence=conflict_min_confidence)
        return analyze_graph(
            self._graph,
            self._tools,
            duplicates=duplicates,
            conflicts=conflicts,
        )

    # --- presets ---

    def apply_commerce_preset(self, *, min_confidence: float = 0.7) -> int:
        """Apply commerce domain workflow patterns (PRECEDES relations).

        Returns the number of relations added.
        """
        from graph_tool_call.presets.commerce import apply_commerce_preset

        added = apply_commerce_preset(self, min_confidence=min_confidence)
        if added:
            self._invalidate_retrieval()
        return added

    # --- assist: validation & suggestion ---

    def validate_tool_call(
        self,
        call: dict[str, Any],
        *,
        fuzzy_threshold: float = 0.7,
    ) -> Any:
        """Validate and auto-correct a tool call.

        Checks tool name (exact → case-insensitive → fuzzy), required params,
        param name typos, and enum values. Returns a ``ValidationResult``
        with corrected values and warnings.

        Example::

            result = tg.validate_tool_call({"name": "deleteuser", "arguments": {"id": "123"}})
            if not result.valid:
                print(result.corrections)  # {"name": ("deleteuser", "deleteUser")}
                # Use result.tool_name and result.arguments for the corrected call
        """
        from graph_tool_call.assist.validator import validate_tool_call as _validate

        return _validate(call, self._tools, fuzzy_threshold=fuzzy_threshold)

    def assess_tool_call(
        self,
        call: dict[str, Any],
        *,
        policy: Any = None,
        fuzzy_threshold: float = 0.7,
    ) -> Any:
        """Assess whether a tool call should be allowed, confirmed, or denied.

        This wraps ``validate_tool_call()`` with an execution policy layer.
        The returned assessment includes the corrected tool name/arguments and a
        final decision: ``allow``, ``confirm``, or ``deny``.
        """
        from graph_tool_call.assist.policy import assess_tool_call as _assess

        return _assess(
            call,
            self._tools,
            policy=policy,
            fuzzy_threshold=fuzzy_threshold,
        )

    def suggest_next(
        self,
        current_tool: str,
        *,
        history: list[str] | None = None,
        top_k: int = 5,
    ) -> list[Any]:
        """Suggest next tools based on graph relationships.

        Uses REQUIRES, PRECEDES, and same-domain edges to recommend
        likely next steps after executing ``current_tool``.

        Example::

            suggestions = tg.suggest_next("getUser", history=["listUsers"])
            for s in suggestions:
                print(f"{s.tool.name}: {s.reason}")
        """
        from graph_tool_call.assist.next_step import suggest_next as _suggest

        return _suggest(current_tool, self._graph, self._tools, history=history, top_k=top_k)

    # --- model-driven search API ---

    @property
    def search_api(self) -> Any:
        """Get the Model-Driven Search API for LLM function-calling integration."""
        from graph_tool_call.retrieval.model_driven import ToolGraphSearchAPI

        return ToolGraphSearchAPI(self._graph, self._tools, retrieve_fn=self.retrieve)

    # --- visualization / export ---

    def export_html(
        self,
        path: str | Path,
        *,
        physics: bool = True,
        standalone: bool = False,
        progressive: bool = False,
    ) -> None:
        """Export the graph to an interactive HTML file.

        Parameters
        ----------
        standalone:
            If True, use vis.js CDN directly (no pyvis dependency).
        progressive:
            If True (implies standalone), enable progressive disclosure —
            tools are hidden until their category is double-clicked.
        """
        if progressive:
            standalone = True
        if standalone:
            from graph_tool_call.visualization.html_export import export_html_standalone

            export_html_standalone(self._graph, self._tools, path, progressive=progressive)
        else:
            from graph_tool_call.visualization.html_export import export_html

            export_html(self._graph, self._tools, path, physics=physics)

    def export_graphml(self, path: str | Path) -> None:
        """Export the graph to GraphML format (compatible with Gephi, yEd)."""
        from graph_tool_call.visualization.graphml_export import export_graphml

        export_graphml(self._graph, self._tools, path)

    def export_cypher(self, path: str | Path) -> None:
        """Export the graph as Neo4j Cypher CREATE statements."""
        from graph_tool_call.visualization.cypher_export import export_cypher

        export_cypher(self._graph, self._tools, path)

    def dashboard_app(self, *, title: str = "graph-tool-call Dashboard") -> Any:
        """Build a Dash Cytoscape dashboard app for this graph."""
        from graph_tool_call.dashboard.app import build_dashboard_app

        return build_dashboard_app(self, title=title)

    def dashboard(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8050,
        debug: bool = False,
    ) -> Any:
        """Launch the interactive dashboard server."""
        from graph_tool_call.dashboard.app import launch_dashboard

        return launch_dashboard(self, host=host, port=port, debug=debug)

    # --- info ---

    def __repr__(self) -> str:
        return (
            f"ToolGraph(tools={len(self._tools)}, "
            f"nodes={self._graph.node_count()}, "
            f"edges={self._graph.edge_count()})"
        )
