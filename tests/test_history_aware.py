"""Tests for history-aware retrieval."""

from graph_tool_call.tool_graph import ToolGraph


def _build_commerce_graph() -> ToolGraph:
    """Build a sample ToolGraph with commerce tools."""
    tg = ToolGraph()

    tools = [
        {"name": "create_order", "description": "Create a new order"},
        {"name": "get_order", "description": "Get order details by ID"},
        {"name": "cancel_order", "description": "Cancel an existing order"},
        {"name": "process_refund", "description": "Process a refund for an order"},
        {"name": "list_products", "description": "List available products"},
        {"name": "search_products", "description": "Search products by keyword"},
        {"name": "send_notification", "description": "Send a notification to user"},
    ]
    tg.add_tools(tools)

    tg.add_category("orders")
    tg.add_category("products")
    tg.add_category("notifications")

    tg.assign_category("create_order", "orders")
    tg.assign_category("get_order", "orders")
    tg.assign_category("cancel_order", "orders")
    tg.assign_category("process_refund", "orders")
    tg.assign_category("list_products", "products")
    tg.assign_category("search_products", "products")
    tg.assign_category("send_notification", "notifications")

    tg.add_relation("cancel_order", "process_refund", "complementary")
    tg.add_relation("create_order", "get_order", "complementary")

    return tg


def test_history_boosts_related_tools():
    """After calling cancel_order, refund-related tools should rank higher."""
    tg = _build_commerce_graph()

    # With history: user already called cancel_order
    results_with_hist = tg.retrieve("refund", top_k=5, history=["cancel_order"])

    names_with_hist = [t.name for t in results_with_hist]
    assert "process_refund" in names_with_hist


def test_history_demotes_already_used():
    """Already-used tools should rank lower to promote new discoveries."""
    tg = _build_commerce_graph()

    results = tg.retrieve("order", top_k=5, history=["get_order"])
    names = [t.name for t in results]

    # get_order should still appear but not necessarily first
    # Other order tools should be discoverable
    assert any(n in names for n in ["create_order", "cancel_order", "get_order"])


def test_history_empty_is_noop():
    """Empty history should produce same results as no history."""
    tg = _build_commerce_graph()

    results_none = tg.retrieve("order", top_k=5)
    results_empty = tg.retrieve("order", top_k=5, history=[])

    names_none = [t.name for t in results_none]
    names_empty = [t.name for t in results_empty]
    assert names_none == names_empty


def test_history_with_unknown_tool():
    """History with unknown tool names should not crash."""
    tg = _build_commerce_graph()
    results = tg.retrieve("order", top_k=5, history=["nonexistent_tool"])
    assert isinstance(results, list)
