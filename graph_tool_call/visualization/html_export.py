"""Export ToolGraph to interactive HTML using Pyvis."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph_tool_call.core.protocol import GraphEngine
    from graph_tool_call.core.tool import ToolSchema

try:
    from pyvis.network import Network
except ImportError:
    Network = None  # type: ignore[assignment, misc]

# Node colors by type
_NODE_COLORS = {
    "domain": "#9b59b6",  # purple
    "category": "#3498db",  # blue
    "tool": "#2ecc71",  # green
}

# Node sizes by type
_NODE_SIZES = {
    "domain": 30,
    "category": 22,
    "tool": 15,
}

# Edge colors by relation type
_EDGE_COLORS = {
    "requires": "#e74c3c",  # red
    "precedes": "#e67e22",  # orange
    "complementary": "#2ecc71",  # green
    "similar_to": "#3498db",  # blue
    "conflicts_with": "#95a5a6",  # gray
    "belongs_to": "#bdc3c7",  # light gray
}

_EDGE_DASHES = {
    "similar_to": True,
    "conflicts_with": True,
}


def _require_pyvis() -> None:
    if Network is None:
        msg = "pyvis required: pip install pyvis"
        raise ImportError(msg)


def export_html(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
    *,
    height: str = "800px",
    width: str = "100%",
    physics: bool = True,
) -> None:
    """Export the graph to an interactive HTML file using Pyvis.

    Parameters
    ----------
    graph:
        The graph engine containing nodes and edges.
    tools:
        Tool schemas for tooltip information.
    path:
        Output HTML file path.
    height, width:
        Dimensions of the visualization.
    physics:
        Whether to enable physics simulation (barnes_hut).
    """
    _require_pyvis()

    net = Network(
        height=height,
        width=width,
        directed=True,
        notebook=False,
        cdn_resources="remote",
    )

    if physics:
        net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=200)
    else:
        net.toggle_physics(False)

    # Add nodes
    for node_id in graph.nodes():
        attrs = graph.get_node_attrs(node_id)
        node_type = str(attrs.get("node_type", "tool")).lower()
        color = _NODE_COLORS.get(node_type, "#2ecc71")
        base_size = _NODE_SIZES.get(node_type, 15)

        # Scale tool nodes by degree
        if node_type == "tool":
            neighbors = graph.get_neighbors(node_id, direction="both")
            degree = len(neighbors)
            size = base_size + min(degree * 2, 20)
        else:
            size = base_size

        # Build tooltip
        title_parts = [f"<b>{node_id}</b>", f"Type: {node_type}"]
        desc = attrs.get("description", "")
        if desc:
            # Truncate long descriptions
            if len(str(desc)) > 200:
                desc = str(desc)[:200] + "..."
            title_parts.append(f"Description: {desc}")
        tags = attrs.get("tags")
        if tags:
            title_parts.append(f"Tags: {', '.join(str(t) for t in tags)}")
        if node_id in tools:
            tool = tools[node_id]
            param_names = [p.name for p in tool.parameters]
            if param_names:
                title_parts.append(f"Params: {', '.join(param_names)}")
        title = "<br>".join(title_parts)

        net.add_node(node_id, label=node_id, color=color, size=size, title=title)

    # Add edges
    for src, tgt, attrs in graph.edges():
        relation = str(attrs.get("relation", "related_to")).lower()
        color = _EDGE_COLORS.get(relation, "#7f8c8d")
        dashes = _EDGE_DASHES.get(relation, False)
        weight = attrs.get("weight", 1.0)
        title = relation
        if "confidence" in attrs:
            title += f" (conf: {attrs['confidence']:.2f})"

        net.add_edge(
            src,
            tgt,
            color=color,
            dashes=dashes,
            width=max(1, float(weight) * 2),
            title=title,
            arrows="to",
        )

    net.save_graph(str(path))
