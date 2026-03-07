"""Model-Driven Search API — LLM-friendly tool graph query methods."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graph_tool_call.ontology.schema import NodeType, RelationType

if TYPE_CHECKING:
    from graph_tool_call.core.protocol import GraphEngine
    from graph_tool_call.core.tool import ToolSchema


class ToolGraphSearchAPI:
    """Structured search API that can be exposed as LLM function-calling tools.

    Provides ``search_tools``, ``get_workflow``, and ``browse_categories``
    for agent-driven tool discovery.
    """

    def __init__(
        self,
        graph: GraphEngine,
        tools: dict[str, ToolSchema],
        retrieve_fn: Any = None,
    ) -> None:
        self._graph = graph
        self._tools = tools
        self._retrieve_fn = retrieve_fn

    def search_tools(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search tools by natural language query.

        Returns a list of dicts with ``name``, ``description``, and ``parameters``.
        """
        if self._retrieve_fn is None:
            return []
        results = self._retrieve_fn(query, top_k=top_k)
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": [
                    {"name": p.name, "type": p.type, "required": p.required} for p in t.parameters
                ],
            }
            for t in results
        ]

    def get_workflow(self, tool_name: str) -> list[str]:
        """Get the workflow chain for a tool by following PRECEDES relations.

        Returns an ordered list of tool names representing the execution sequence.
        Follows PRECEDES edges both backward (predecessors) and forward (successors).
        """
        if not self._graph.has_node(tool_name):
            return []

        # Walk backward to find the chain start
        chain_start = tool_name
        visited: set[str] = {tool_name}
        current = tool_name
        while True:
            predecessors = self._get_precedes_neighbors(current, direction="in")
            predecessors = [p for p in predecessors if p not in visited]
            if not predecessors:
                break
            chain_start = predecessors[0]
            visited.add(chain_start)
            current = chain_start

        # Walk forward from chain_start
        result: list[str] = [chain_start]
        visited_forward: set[str] = {chain_start}
        current = chain_start
        while True:
            successors = self._get_precedes_neighbors(current, direction="out")
            successors = [s for s in successors if s not in visited_forward]
            if not successors:
                break
            next_tool = successors[0]
            result.append(next_tool)
            visited_forward.add(next_tool)
            current = next_tool

        return result

    def browse_categories(self) -> dict[str, Any]:
        """Browse the ontology tree: domains → categories → tools.

        Returns a nested dict structure for LLM consumption.
        """
        tree: dict[str, Any] = {"domains": {}, "uncategorized": []}

        # Collect categories and their tools
        categories: dict[str, list[str]] = {}
        category_domains: dict[str, str | None] = {}

        for node_id in self._graph.nodes():
            attrs = self._graph.get_node_attrs(node_id)
            node_type = attrs.get("node_type")
            if node_type == NodeType.CATEGORY:
                cat_tools = []
                for neighbor in self._graph.get_neighbors(node_id, direction="in"):
                    n_attrs = self._graph.get_node_attrs(neighbor)
                    if n_attrs.get("node_type") == NodeType.TOOL:
                        if self._graph.has_edge(neighbor, node_id):
                            edge = self._graph.get_edge_attrs(neighbor, node_id)
                            if edge.get("relation") == RelationType.BELONGS_TO:
                                cat_tools.append(neighbor)
                categories[node_id] = sorted(cat_tools)

                # Find domain
                for neighbor in self._graph.get_neighbors(node_id, direction="out"):
                    n_attrs = self._graph.get_node_attrs(neighbor)
                    if n_attrs.get("node_type") == NodeType.DOMAIN:
                        if self._graph.has_edge(node_id, neighbor):
                            category_domains[node_id] = neighbor
                            break
                if node_id not in category_domains:
                    category_domains[node_id] = None

        # Build tree
        for cat, cat_tools in categories.items():
            domain = category_domains.get(cat)
            entry = {"tools": cat_tools, "tool_count": len(cat_tools)}
            if domain:
                if domain not in tree["domains"]:
                    tree["domains"][domain] = {"categories": {}}
                tree["domains"][domain]["categories"][cat] = entry
            else:
                if "categories" not in tree:
                    tree["categories"] = {}
                tree["categories"][cat] = entry

        # Find uncategorized tools
        categorized_tools: set[str] = set()
        for cat_tools in categories.values():
            categorized_tools.update(cat_tools)
        for node_id in self._graph.nodes():
            attrs = self._graph.get_node_attrs(node_id)
            if attrs.get("node_type") == NodeType.TOOL and node_id not in categorized_tools:
                tree["uncategorized"].append(node_id)
        tree["uncategorized"].sort()

        return tree

    def _get_precedes_neighbors(self, node_id: str, direction: str) -> list[str]:
        """Get neighbors connected via PRECEDES relation."""
        result: list[str] = []
        for edge in self._graph.get_edges_from(node_id, direction=direction):
            src, tgt, attrs = edge
            if attrs.get("relation") == RelationType.PRECEDES:
                other = tgt if src == node_id else src
                result.append(other)
        return result
