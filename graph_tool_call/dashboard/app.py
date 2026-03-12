"""Dash Cytoscape dashboard for inspecting a ToolGraph."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from graph_tool_call.ontology.schema import NodeType

if TYPE_CHECKING:
    from graph_tool_call.tool_graph import ToolGraph

_NODE_COLORS = {
    "domain": "#c06c84",
    "category": "#355c7d",
    "tool": "#6c9a3b",
}

_EDGE_COLORS = {
    "requires": "#d62828",
    "precedes": "#f77f00",
    "complementary": "#277da1",
    "similar_to": "#8d99ae",
    "conflicts_with": "#6d597a",
    "belongs_to": "#495057",
}


def _node_type_label(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "unknown").lower()


def _relation_label(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).lower()
    return str(value or "unknown").lower()


def _build_elements(tg: ToolGraph) -> list[dict[str, Any]]:
    """Convert graph nodes and edges to Cytoscape elements."""
    elements: list[dict[str, Any]] = []

    for node_id in tg.graph.nodes():
        attrs = tg.graph.get_node_attrs(node_id)
        node_type = _node_type_label(attrs.get("node_type"))
        tool = tg.tools.get(node_id)
        category = ""
        if node_type == NodeType.TOOL.value:
            for _, target, edge_attrs in tg.graph.get_edges_from(node_id, direction="out"):
                if _relation_label(edge_attrs.get("relation", "")) == "belongs_to":
                    category = target
                    break

        elements.append(
            {
                "data": {
                    "id": node_id,
                    "label": node_id,
                    "node_type": node_type,
                    "description": getattr(tool, "description", attrs.get("description", "")),
                    "tags": ", ".join(getattr(tool, "tags", []) or []),
                    "category": category,
                }
            }
        )

    for source, target, attrs in tg.graph.edges():
        relation = _relation_label(attrs.get("relation", "unknown"))
        elements.append(
            {
                "data": {
                    "id": f"{source}->{target}:{relation}",
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "confidence": float(attrs.get("confidence", 1.0)),
                }
            }
        )

    return elements


def _detail_text(tg: ToolGraph, node_id: str | None) -> str:
    """Render a readable detail summary for the selected node."""
    if not node_id or not tg.graph.has_node(node_id):
        return "Select a node to inspect details."

    attrs = tg.graph.get_node_attrs(node_id)
    node_type = _node_type_label(attrs.get("node_type"))
    lines = [f"name: {node_id}", f"type: {node_type}"]
    tool = tg.tools.get(node_id)
    if tool is not None:
        if tool.description:
            lines.append(f"description: {tool.description}")
        if tool.tags:
            lines.append(f"tags: {', '.join(tool.tags)}")
        if tool.parameters:
            params = ", ".join(
                f"{param.name}{' *' if param.required else ''}:{param.type}"
                for param in tool.parameters
            )
            lines.append(f"parameters: {params}")

    relations = []
    for source, target, edge_attrs in tg.graph.get_edges_from(node_id, direction="both"):
        relation = _relation_label(edge_attrs.get("relation", "unknown"))
        if source == node_id:
            relations.append(f"{relation} -> {target}")
        else:
            relations.append(f"{relation} <- {source}")
    if relations:
        lines.append("relations:")
        lines.extend(relations[:12])
    return "\n".join(lines)


def _filter_elements(
    elements: list[dict[str, Any]],
    *,
    allowed_relations: set[str],
    selected_category: str | None,
    highlighted_nodes: set[str],
) -> list[dict[str, Any]]:
    """Apply relation/category filters and optional query highlights."""
    nodes_by_id = {item["data"]["id"]: item for item in elements if "source" not in item["data"]}
    visible_nodes = set(nodes_by_id)
    if selected_category:
        visible_nodes = {
            node_id
            for node_id, node in nodes_by_id.items()
            if node["data"].get("node_type") != NodeType.TOOL.value
            or node["data"].get("category") == selected_category
        }

    filtered: list[dict[str, Any]] = []
    for item in elements:
        data = item["data"]
        if "source" not in data:
            node = {"data": dict(data)}
            classes = []
            if data["id"] in highlighted_nodes:
                classes.append("highlighted")
            if data["id"] not in visible_nodes:
                classes.append("filtered-out")
            if classes:
                node["classes"] = " ".join(classes)
            filtered.append(node)
            continue

        if data.get("relation") not in allowed_relations:
            continue
        if data["source"] not in visible_nodes or data["target"] not in visible_nodes:
            continue
        edge = {"data": dict(data)}
        if data["source"] in highlighted_nodes or data["target"] in highlighted_nodes:
            edge["classes"] = "highlighted"
        filtered.append(edge)

    return filtered


def build_dashboard_app(tg: ToolGraph, *, title: str = "graph-tool-call Dashboard") -> Any:
    """Create a Dash Cytoscape app for interactive graph inspection."""
    try:
        import dash_cytoscape as cyto
        from dash import Dash, Input, Output, dcc, html
    except ImportError as exc:  # pragma: no cover
        msg = "dashboard extras required: pip install graph-tool-call[dashboard]"
        raise ImportError(msg) from exc

    elements = _build_elements(tg)
    categories = sorted(
        node["data"]["label"]
        for node in elements
        if node["data"].get("node_type") == NodeType.CATEGORY.value
    )
    relation_options = sorted(
        item["data"]["relation"] for item in elements if "source" in item["data"]
    )

    app = Dash(__name__)
    app.title = title
    app.layout = html.Div(
        [
            html.H2(title),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Relations"),
                            dcc.Checklist(
                                id="relation-filter",
                                options=[{"label": rel, "value": rel} for rel in relation_options],
                                value=relation_options,
                            ),
                            html.Label("Category"),
                            dcc.Dropdown(
                                id="category-filter",
                                options=[{"label": cat, "value": cat} for cat in categories],
                                placeholder="All categories",
                                clearable=True,
                            ),
                            html.Label("Search"),
                            dcc.Input(id="query", type="text", placeholder="Find tools"),
                            html.Pre(
                                id="node-detail",
                                children="Select a node to inspect details.",
                                style={"whiteSpace": "pre-wrap"},
                            ),
                        ],
                        style={"width": "28%", "padding": "1rem"},
                    ),
                    html.Div(
                        [
                            dcc.Store(id="all-elements", data=elements),
                            cyto.Cytoscape(
                                id="tool-graph",
                                layout={"name": "cose"},
                                style={"width": "100%", "height": "720px"},
                                elements=elements,
                                stylesheet=[
                                    {
                                        "selector": "node",
                                        "style": {
                                            "label": "data(label)",
                                            "font-size": 12,
                                            "text-wrap": "wrap",
                                            "text-max-width": 120,
                                        },
                                    },
                                    {
                                        "selector": '[node_type = "domain"]',
                                        "style": {"background-color": _NODE_COLORS["domain"]},
                                    },
                                    {
                                        "selector": '[node_type = "category"]',
                                        "style": {"background-color": _NODE_COLORS["category"]},
                                    },
                                    {
                                        "selector": '[node_type = "tool"]',
                                        "style": {"background-color": _NODE_COLORS["tool"]},
                                    },
                                    {
                                        "selector": "edge",
                                        "style": {
                                            "curve-style": "bezier",
                                            "target-arrow-shape": "triangle",
                                            "line-color": "#adb5bd",
                                            "target-arrow-color": "#adb5bd",
                                            "label": "data(relation)",
                                            "font-size": 9,
                                        },
                                    },
                                    *[
                                        {
                                            "selector": f'[relation = "{relation}"]',
                                            "style": {
                                                "line-color": color,
                                                "target-arrow-color": color,
                                            },
                                        }
                                        for relation, color in _EDGE_COLORS.items()
                                    ],
                                    {
                                        "selector": ".highlighted",
                                        "style": {
                                            "border-width": 3,
                                            "border-color": "#ffb703",
                                            "line-color": "#ffb703",
                                            "target-arrow-color": "#ffb703",
                                        },
                                    },
                                    {"selector": ".filtered-out", "style": {"opacity": 0.15}},
                                ],
                            ),
                        ],
                        style={"width": "72%", "padding": "1rem"},
                    ),
                ],
                style={"display": "flex", "gap": "1rem"},
            ),
        ],
        style={"fontFamily": "sans-serif", "padding": "1rem"},
    )

    @app.callback(
        Output("tool-graph", "elements"),
        Input("relation-filter", "value"),
        Input("category-filter", "value"),
        Input("query", "value"),
        Input("all-elements", "data"),
    )
    def _update_elements(
        selected_relations: list[str] | None,
        selected_category: str | None,
        query: str | None,
        all_elements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        relations = set(selected_relations or relation_options)
        highlighted = set()
        if query:
            highlighted = {tool.name for tool in tg.retrieve(query, top_k=5)}
        return _filter_elements(
            all_elements,
            allowed_relations=relations,
            selected_category=selected_category,
            highlighted_nodes=highlighted,
        )

    @app.callback(Output("node-detail", "children"), Input("tool-graph", "tapNodeData"))
    def _update_detail(node_data: dict[str, Any] | None) -> str:
        node_id = None if not node_data else node_data.get("id")
        return _detail_text(tg, node_id)

    return app


def launch_dashboard(
    tg: ToolGraph,
    *,
    host: str = "127.0.0.1",
    port: int = 8050,
    debug: bool = False,
) -> Any:
    """Launch the interactive dashboard and block until the server stops."""
    app = build_dashboard_app(tg)
    app.run(host=host, port=port, debug=debug)
    return app
