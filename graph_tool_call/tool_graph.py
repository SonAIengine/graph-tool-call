"""ToolGraph — main public API facade."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema, parse_tool
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import RelationType
from graph_tool_call.retrieval.engine import RetrievalEngine, SearchMode
from graph_tool_call.serialization import load_graph, save_graph


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

    async def auto_organize(self, llm: Any = None) -> None:
        """Automatically organize tools using LLM (Phase 2)."""
        from graph_tool_call.ontology.auto import auto_organize

        await auto_organize(self._builder, list(self._tools.values()), llm)

    # --- retrieval ---

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        max_graph_depth: int = 2,
        mode: str | SearchMode = SearchMode.BASIC,
    ) -> list[ToolSchema]:
        """Retrieve the most relevant tools for a query."""
        engine = self._get_retrieval_engine()
        return engine.retrieve(query, top_k=top_k, max_graph_depth=max_graph_depth, mode=mode)

    def _get_retrieval_engine(self) -> RetrievalEngine:
        if self._retrieval is None:
            self._retrieval = RetrievalEngine(self._graph, self._tools)
        return self._retrieval

    def _invalidate_retrieval(self) -> None:
        self._retrieval = None

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

    # --- info ---

    def __repr__(self) -> str:
        return (
            f"ToolGraph(tools={len(self._tools)}, "
            f"nodes={self._graph.node_count()}, "
            f"edges={self._graph.edge_count()})"
        )
