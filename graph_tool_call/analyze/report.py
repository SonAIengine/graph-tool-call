"""Higher-level graph analysis summaries for CLI and dashboards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from graph_tool_call.analyze.conflict import ConflictResult
from graph_tool_call.analyze.similarity import DuplicatePair
from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType


def _enum_label(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


@dataclass
class CategorySummary:
    """Summary of a category node and its assigned tools."""

    name: str
    domain: str | None
    tool_count: int


@dataclass
class GraphAnalysisReport:
    """Serializable summary for operational graph inspection."""

    tool_count: int
    node_count: int
    edge_count: int
    duplicate_count: int
    conflict_count: int
    orphan_tool_count: int
    category_count: int
    relation_counts: dict[str, int]
    node_type_counts: dict[str, int]
    orphan_tools: list[str]
    categories: list[CategorySummary]
    duplicates: list[DuplicatePair]
    conflicts: list[ConflictResult]

    def to_dict(self) -> dict[str, Any]:
        """Convert the report to a JSON-serializable dict."""
        return {
            "tool_count": self.tool_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "duplicate_count": self.duplicate_count,
            "conflict_count": self.conflict_count,
            "orphan_tool_count": self.orphan_tool_count,
            "category_count": self.category_count,
            "relation_counts": dict(self.relation_counts),
            "node_type_counts": dict(self.node_type_counts),
            "orphan_tools": list(self.orphan_tools),
            "categories": [asdict(category) for category in self.categories],
            "duplicates": [asdict(duplicate) for duplicate in self.duplicates],
            "conflicts": [asdict(conflict) for conflict in self.conflicts],
        }


def analyze_graph(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    *,
    duplicates: list[DuplicatePair] | None = None,
    conflicts: list[ConflictResult] | None = None,
) -> GraphAnalysisReport:
    """Build an operational summary from the current graph state."""
    node_type_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}

    for node_id in graph.nodes():
        node_type = _enum_label(graph.get_node_attrs(node_id).get("node_type", "unknown"))
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

    for _, _, attrs in graph.edges():
        relation = _enum_label(attrs.get("relation", "unknown"))
        relation_counts[relation] = relation_counts.get(relation, 0) + 1

    orphan_tools: list[str] = []
    categories: list[CategorySummary] = []

    for node_id in graph.nodes():
        attrs = graph.get_node_attrs(node_id)
        node_type = attrs.get("node_type")
        if node_type == NodeType.TOOL:
            if not graph.get_neighbors(node_id, direction="both"):
                orphan_tools.append(node_id)
        elif node_type == NodeType.CATEGORY:
            incoming_tools = [
                neighbor
                for neighbor in graph.get_neighbors(node_id, direction="in")
                if graph.get_node_attrs(neighbor).get("node_type") == NodeType.TOOL
            ]
            domain = None
            for source, _, edge_attrs in graph.get_edges_from(node_id, direction="in"):
                if (
                    graph.get_node_attrs(source).get("node_type") == NodeType.DOMAIN
                    and _enum_label(edge_attrs.get("relation", "")).lower() == "belongs_to"
                ):
                    domain = source
                    break
            categories.append(
                CategorySummary(
                    name=node_id,
                    domain=domain,
                    tool_count=len(incoming_tools),
                )
            )

    orphan_tools.sort()
    categories.sort(key=lambda item: (-item.tool_count, item.name))
    duplicate_items = list(duplicates or [])
    conflict_items = list(conflicts or [])

    return GraphAnalysisReport(
        tool_count=len(tools),
        node_count=graph.node_count(),
        edge_count=graph.edge_count(),
        duplicate_count=len(duplicate_items),
        conflict_count=len(conflict_items),
        orphan_tool_count=len(orphan_tools),
        category_count=len(categories),
        relation_counts=dict(sorted(relation_counts.items())),
        node_type_counts=dict(sorted(node_type_counts.items())),
        orphan_tools=orphan_tools,
        categories=categories,
        duplicates=duplicate_items,
        conflicts=conflict_items,
    )
