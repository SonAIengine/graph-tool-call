"""Export ToolGraph to GraphML format (compatible with Gephi, yEd, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graph_tool_call.core.protocol import GraphEngine
    from graph_tool_call.core.tool import ToolSchema


def export_graphml(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
) -> None:
    """Export the graph to GraphML format.

    Uses NetworkX's built-in GraphML writer. Node and edge attributes
    are preserved as GraphML data keys.
    """
    import networkx as nx

    g = _to_networkx(graph, tools)
    nx.write_graphml(g, str(path))


def _to_networkx(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
) -> Any:
    """Convert GraphEngine to a plain NetworkX DiGraph with string-safe attributes."""
    import networkx as nx

    g = nx.DiGraph()

    for node_id in graph.nodes():
        attrs = graph.get_node_attrs(node_id)
        safe: dict[str, str] = {}
        raw_type = attrs.get("node_type", "")
        safe["node_type"] = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
        safe["description"] = str(attrs.get("description", ""))
        if "tags" in attrs and attrs["tags"]:
            safe["tags"] = ",".join(str(t) for t in attrs["tags"])
        if "domain" in attrs and attrs["domain"]:
            safe["domain"] = str(attrs["domain"])
        # Add tool parameter count if available
        if node_id in tools:
            safe["param_count"] = str(len(tools[node_id].parameters))
        g.add_node(node_id, **safe)

    for src, tgt, attrs in graph.edges():
        safe_edge: dict[str, str] = {}
        if "relation" in attrs:
            raw_rel = attrs["relation"]
            safe_edge["relation"] = raw_rel.value if hasattr(raw_rel, "value") else str(raw_rel)
        if "weight" in attrs:
            safe_edge["weight"] = str(attrs["weight"])
        if "confidence" in attrs:
            safe_edge["confidence"] = str(attrs["confidence"])
        g.add_edge(src, tgt, **safe_edge)

    return g
