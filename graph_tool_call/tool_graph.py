"""ToolGraph — main public API facade."""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema, parse_tool
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import RelationType
from graph_tool_call.retrieval.engine import RetrievalEngine, SearchMode
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


def _discover_spec_urls(url: str) -> list[str]:
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
        result = _try_swagger_config(config_url, base)
        if result:
            return result

    # Step 2: Parse swagger-initializer.js to find configUrl
    init_js_url = f"{ui_base}/swagger-initializer.js"
    try:
        with urllib.request.urlopen(init_js_url) as resp:  # noqa: S310
            js_text = resp.read().decode("utf-8")
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
            result = _try_swagger_config(config_url, base)
            if result:
                return result
    except Exception:  # noqa: BLE001
        pass

    # Step 3: Fallback
    return [f"{base}/v3/api-docs"]


def _try_swagger_config(config_url: str, base: str) -> list[str] | None:
    """Try fetching a swagger-config URL and extract spec URLs."""
    try:
        with urllib.request.urlopen(config_url) as resp:  # noqa: S310
            config = json.loads(resp.read().decode("utf-8"))
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
        self._tools[schema.name] = schema
        self._builder.add_tool(schema)
        self._invalidate_retrieval()
        return schema

    def add_tools(self, tools: list[Any]) -> list[ToolSchema]:
        """Add multiple tools (auto-detects format for each)."""
        return [self.add_tool(t) for t in tools]

    # --- ingest ---

    def ingest_openapi(
        self,
        source: dict[str, Any] | str,
        *,
        required_only: bool = False,
        skip_deprecated: bool = True,
        detect_dependencies: bool = True,
        min_confidence: float = 0.7,
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
            source, required_only=required_only, skip_deprecated=skip_deprecated
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

        for schema in schemas:
            self._tools[schema.name] = schema
            self._builder.add_tool(schema)

        if detect_dependencies and len(schemas) >= 2:
            from graph_tool_call.analyze.dependency import detect_dependencies as _detect

            relations = _detect(schemas, min_confidence=min_confidence)
            for rel in relations:
                self._builder.add_relation(rel.source, rel.target, rel.relation_type)

        self._invalidate_retrieval()
        return schemas

    def ingest_functions(self, fns: Iterable[Callable[..., Any]]) -> list[ToolSchema]:
        """Ingest Python callables into the tool graph.

        Uses ``inspect.signature`` and type hints to extract parameters.

        Returns
        -------
        list[ToolSchema]
            The ingested tool schemas.
        """
        from graph_tool_call.ingest.functions import ingest_functions

        tools = ingest_functions(fns)
        for tool in tools:
            self._tools[tool.name] = tool
            self._builder.add_tool(tool)
        self._invalidate_retrieval()
        return tools

    def ingest_arazzo(self, source: Any) -> list:
        """Ingest an Arazzo 1.0.0 workflow spec, adding PRECEDES relations.

        Only adds relations between tools already registered in the graph.

        Returns
        -------
        list[ArazzoRelation]
            The detected workflow relations.
        """
        from graph_tool_call.ingest.arazzo import ingest_arazzo

        relations = ingest_arazzo(source, registered_tools=set(self._tools.keys()))
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
        """Automatically organize tools using LLM (Phase 2)."""
        from graph_tool_call.ontology.auto import auto_organize

        auto_organize(self._builder, list(self._tools.values()), llm)

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

    def enable_embedding(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Enable embedding-based hybrid search using a sentence-transformers model.

        Builds embeddings for all registered tools and attaches the index
        to the retrieval engine.  Weights are automatically rebalanced to
        graph=0.5, keyword=0.2, embedding=0.3.
        """
        from graph_tool_call.retrieval.embedding import EmbeddingIndex

        index = EmbeddingIndex(model_name=model_name)
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
    ) -> ToolGraph:
        """Create a ToolGraph by fetching OpenAPI spec(s) from a URL.

        Supports:
        - Direct spec URLs (JSON/YAML)
        - Swagger UI URLs (auto-discovers specs via swagger-config)
        """
        spec_urls = _discover_spec_urls(url)
        tg = cls()
        for spec_url in spec_urls:
            tg.ingest_openapi(
                spec_url,
                required_only=required_only,
                skip_deprecated=skip_deprecated,
                detect_dependencies=detect_dependencies,
                min_confidence=min_confidence,
            )
        return tg

    # --- serialization ---

    def save(self, path: str | Path) -> None:
        """Save the tool graph to a JSON file."""
        save_graph(self._graph, self._tools, path)

    @classmethod
    def load(cls, path: str | Path) -> ToolGraph:
        """Load a tool graph from a JSON file."""
        graph, tools = load_graph(path)
        tg = cls(graph=graph)
        tg._tools = tools
        return tg

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

    # --- info ---

    def __repr__(self) -> str:
        return (
            f"ToolGraph(tools={len(self._tools)}, "
            f"nodes={self._graph.node_count()}, "
            f"edges={self._graph.edge_count()})"
        )
