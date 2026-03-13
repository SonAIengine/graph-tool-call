"""Tests for dashboard helpers."""

from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.dashboard.app import _build_elements, _detail_text, _filter_elements


def _make_graph() -> ToolGraph:
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="get_user", description="Get user"))
    tg.add_tool(ToolSchema(name="delete_user", description="Delete user"))
    tg.add_category("user_ops")
    tg.assign_category("get_user", "user_ops")
    tg.assign_category("delete_user", "user_ops")
    tg.add_relation("delete_user", "get_user", "conflicts_with")
    return tg


def test_build_elements_contains_nodes_and_edges():
    tg = _make_graph()
    elements = _build_elements(tg)

    node_ids = {item["data"]["id"] for item in elements if "source" not in item["data"]}
    edge_relations = {item["data"]["relation"] for item in elements if "source" in item["data"]}

    assert {"get_user", "delete_user", "user_ops"}.issubset(node_ids)
    assert "conflicts_with" in edge_relations


def test_detail_text_renders_tool_metadata():
    tg = _make_graph()
    text = _detail_text(tg, "get_user")

    assert "name: get_user" in text
    assert "description: Get user" in text
    assert "relations:" in text


def test_filter_elements_keeps_highlight_and_category_selection():
    tg = _make_graph()
    elements = _build_elements(tg)
    filtered = _filter_elements(
        elements,
        allowed_relations={"conflicts_with", "belongs_to"},
        selected_category="user_ops",
        highlighted_nodes={"get_user"},
    )

    highlighted = [item for item in filtered if item.get("classes") == "highlighted"]
    assert highlighted
    assert any(item["data"]["id"] == "get_user" for item in highlighted)
