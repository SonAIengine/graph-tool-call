"""Manual ontology builder — add tools, relations, categories, and domains."""

from __future__ import annotations

from graph_tool_call.core.graph import NetworkXGraph
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType, RelationType


class OntologyBuilder:
    """Builds an ontology graph from tools and explicit relations."""

    def __init__(self, graph: GraphEngine | None = None) -> None:
        self._graph: GraphEngine = graph if graph is not None else NetworkXGraph()

    @property
    def graph(self) -> GraphEngine:
        return self._graph

    # --- tool registration ---

    def add_tool(self, tool: ToolSchema) -> None:
        """Register a tool as a node in the graph."""
        kwargs: dict = {
            "node_type": NodeType.TOOL,
            "description": tool.description,
            "tags": tool.tags,
            "domain": tool.domain,
        }
        if tool.annotations is not None:
            kwargs["annotations"] = tool.annotations.to_mcp_dict()
        self._graph.add_node(tool.name, **kwargs)

    def add_tools(self, tools: list[ToolSchema]) -> None:
        for t in tools:
            self.add_tool(t)

    # --- hierarchy ---

    def add_domain(self, domain: str, description: str = "") -> None:
        """Add a domain node."""
        self._graph.add_node(domain, node_type=NodeType.DOMAIN, description=description)

    def add_category(self, category: str, domain: str | None = None, description: str = "") -> None:
        """Add a category node and optionally link to a domain."""
        self._graph.add_node(category, node_type=NodeType.CATEGORY, description=description)
        if domain is not None:
            if not self._graph.has_node(domain):
                self.add_domain(domain)
            self._graph.add_edge(category, domain, relation=RelationType.BELONGS_TO)

    def assign_category(self, tool_name: str, category: str) -> None:
        """Assign a tool to a category (creates BELONGS_TO edge)."""
        if not self._graph.has_node(category):
            self.add_category(category)
        self._graph.add_edge(tool_name, category, relation=RelationType.BELONGS_TO)

    # --- relations ---

    def add_relation(
        self,
        source: str,
        target: str,
        relation: str | RelationType,
        weight: float = 1.0,
    ) -> None:
        """Add a directed relation between two nodes."""
        if isinstance(relation, str):
            relation = RelationType(relation)
        self._graph.add_edge(source, target, relation=relation, weight=weight)

    # --- queries ---

    def get_tools_in_category(self, category: str) -> list[str]:
        """Get all tool names belonging to a category."""
        result: list[str] = []
        for neighbor in self._graph.get_neighbors(category, direction="in"):
            attrs = self._graph.get_node_attrs(neighbor)
            if attrs.get("node_type") == NodeType.TOOL:
                edge_attrs = self._graph.get_edge_attrs(neighbor, category)
                if edge_attrs.get("relation") == RelationType.BELONGS_TO:
                    result.append(neighbor)
        return result

    def get_categories_for_tool(self, tool_name: str) -> list[str]:
        """Get all categories a tool belongs to."""
        result: list[str] = []
        for _, target, attrs in self._graph.get_edges_from(tool_name, direction="out"):
            if attrs.get("relation") == RelationType.BELONGS_TO:
                target_attrs = self._graph.get_node_attrs(target)
                if target_attrs.get("node_type") == NodeType.CATEGORY:
                    result.append(target)
        return result

    def get_related_tools(
        self, tool_name: str, relation: RelationType | None = None
    ) -> list[tuple[str, RelationType]]:
        """Get tools related to the given tool, optionally filtered by relation type."""
        result: list[tuple[str, RelationType]] = []
        for edge in self._graph.get_edges_from(tool_name, direction="both"):
            src, tgt, attrs = edge
            other = tgt if src == tool_name else src
            other_attrs = self._graph.get_node_attrs(other)
            if other_attrs.get("node_type") != NodeType.TOOL:
                continue
            edge_rel = attrs.get("relation")
            if relation is not None and edge_rel != relation:
                continue
            result.append((other, edge_rel))
        return result
