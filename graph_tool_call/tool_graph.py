"""ToolGraph — main public API facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema, parse_tool
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import RelationType
from graph_tool_call.retrieval.engine import RetrievalEngine
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
    ) -> list[ToolSchema]:
        """Retrieve the most relevant tools for a query."""
        engine = self._get_retrieval_engine()
        return engine.retrieve(query, top_k=top_k, max_graph_depth=max_graph_depth)

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
