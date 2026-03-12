"""Export ToolGraph to interactive HTML using Pyvis."""

from __future__ import annotations

import html
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


def _escape_html(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_json_for_script(value: object) -> str:
    import json as _json

    text = _json.dumps(value, ensure_ascii=False)
    # Prevent inline </script> termination and HTML comment edge cases.
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


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
        title_parts = [f"<b>{_escape_html(node_id)}</b>", f"Type: {_escape_html(node_type)}"]
        desc = attrs.get("description", "")
        if desc:
            # Truncate long descriptions
            if len(str(desc)) > 200:
                desc = str(desc)[:200] + "..."
            title_parts.append(f"Description: {_escape_html(desc)}")
        tags = attrs.get("tags")
        if tags:
            title_parts.append(f"Tags: {_escape_html(', '.join(str(t) for t in tags))}")
        if node_id in tools:
            tool = tools[node_id]
            param_names = [p.name for p in tool.parameters]
            if param_names:
                title_parts.append(f"Params: {_escape_html(', '.join(param_names))}")
        title = "<br>".join(title_parts)

        net.add_node(node_id, label=str(node_id), color=color, size=size, title=title)

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


def export_html_standalone(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
    *,
    progressive: bool = False,
) -> None:
    """Export to a standalone HTML file using vis.js CDN (no pyvis needed).

    Parameters
    ----------
    progressive:
        If True, enable progressive disclosure — initially show only
        domains and categories, with tools hidden until a category is clicked.
        Useful for graphs with 100+ nodes.
    """
    nodes_data: list[dict] = []
    edges_data: list[dict] = []

    for node_id in graph.nodes():
        attrs = graph.get_node_attrs(node_id)
        raw_type = attrs.get("node_type", "tool")
        node_type = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
        color = _NODE_COLORS.get(node_type.lower(), "#2ecc71")
        base_size = _NODE_SIZES.get(node_type.lower(), 15)

        hidden = False
        if progressive and node_type.lower() == "tool":
            hidden = True

        node_entry: dict = {
            "id": node_id,
            "label": node_id,
            "color": color,
            "size": base_size,
            "nodeType": node_type.lower(),
            "hidden": hidden,
        }
        desc = attrs.get("description", "")
        if desc:
            node_entry["title"] = str(desc)[:200]
        nodes_data.append(node_entry)

    for src, tgt, attrs in graph.edges():
        raw_rel = attrs.get("relation", "related_to")
        relation = raw_rel.value if hasattr(raw_rel, "value") else str(raw_rel)
        color = _EDGE_COLORS.get(relation.lower(), "#7f8c8d")
        dashes = _EDGE_DASHES.get(relation.lower(), False)

        hidden = False
        if progressive:
            # Hide edges connected to hidden tool nodes
            src_attrs = graph.get_node_attrs(src) if graph.has_node(src) else {}
            tgt_attrs = graph.get_node_attrs(tgt) if graph.has_node(tgt) else {}
            src_type = src_attrs.get("node_type", "")
            tgt_type = tgt_attrs.get("node_type", "")
            src_is_tool = (
                src_type.value if hasattr(src_type, "value") else str(src_type)
            ).lower() == "tool"
            tgt_is_tool = (
                tgt_type.value if hasattr(tgt_type, "value") else str(tgt_type)
            ).lower() == "tool"
            if src_is_tool or tgt_is_tool:
                hidden = True

        edges_data.append(
            {
                "from": src,
                "to": tgt,
                "color": {"color": color},
                "dashes": dashes,
                "arrows": "to",
                "title": relation,
                "hidden": hidden,
            }
        )

    nodes_json = _safe_json_for_script(nodes_data)
    edges_json = _safe_json_for_script(edges_data)

    prog_hint = (
        "<hr style='margin:4px 0'><small>Double-click category to expand/collapse</small>"
        if progressive
        else ""
    )

    progressive_js = ""
    if progressive:
        progressive_js = """
        network.on("doubleClick", function(params) {
            if (params.nodes.length === 1) {
                var clickedId = params.nodes[0];
                var clickedNode = nodes.get(clickedId);
                if (clickedNode.nodeType === "category" || clickedNode.nodeType === "domain") {
                    // Toggle visibility of connected tool nodes
                    var connEdges = network.getConnectedEdges(clickedId);
                    connEdges.forEach(function(edgeId) {
                        var edge = edges.get(edgeId);
                        var otherId = edge.from === clickedId ? edge.to : edge.from;
                        var otherNode = nodes.get(otherId);
                        if (otherNode && otherNode.nodeType === "tool") {
                            var isHidden = otherNode.hidden;
                            nodes.update({id: otherId, hidden: !isHidden});
                            // Also toggle edges to/from this tool
                            var toolEdges = network.getConnectedEdges(otherId);
                            toolEdges.forEach(function(te) {
                                edges.update({id: te, hidden: !isHidden});
                            });
                        }
                    });
                }
            }
        });
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>ToolGraph Visualization</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
body {{ margin: 0; font-family: sans-serif; }}
#graph {{ width: 100%; height: 100vh; }}
#legend {{ position: absolute; top: 10px; right: 10px; background: rgba(255,255,255,0.9);
           padding: 10px; border-radius: 5px; font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; margin: 4px 0; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; }}
#info {{ position: absolute; bottom: 10px; left: 10px; background: rgba(255,255,255,0.9);
         padding: 8px; border-radius: 5px; font-size: 12px; }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="legend">
  <b>Node Types</b>
  <div class="legend-item"><div class="legend-dot" style="background:#9b59b6"></div>Domain</div>
  <div class="legend-item"><div class="legend-dot" style="background:#3498db"></div>Category</div>
  <div class="legend-item"><div class="legend-dot" style="background:#2ecc71"></div>Tool</div>
  <hr style="margin:4px 0">
  <b>Relations</b>
  <div class="legend-item">
    <div class="legend-dot" style="background:#e74c3c"></div>requires</div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#e67e22"></div>precedes</div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#2ecc71"></div>complementary</div>
  <div class="legend-item">
    <div class="legend-dot" style="background:#3498db"></div>similar_to</div>
  {prog_hint}
</div>
<div id="info">{len(nodes_data)} nodes, {len(edges_data)} edges</div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});
var container = document.getElementById("graph");
var data = {{ nodes: nodes, edges: edges }};
var options = {{
    physics: {{ barnesHut: {{ gravitationalConstant: -3000, springLength: 200 }} }},
    interaction: {{ hover: true, tooltipDelay: 100 }},
    edges: {{ smooth: {{ type: "continuous" }} }}
}};
var network = new vis.Network(container, data, options);
{progressive_js}
</script>
</body>
</html>"""

    Path(path).write_text(html, encoding="utf-8")
