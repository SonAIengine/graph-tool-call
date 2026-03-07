"""Tests for Model-Driven Search API."""

from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema


def _make_workflow_graph() -> ToolGraph:
    """Create a graph with PRECEDES workflow chain."""
    tg = ToolGraph()
    for name in ["listOrders", "getOrder", "cancelOrder", "processRefund"]:
        tg.add_tool(ToolSchema(name=name, description=f"{name} operation", parameters=[]))
    tg.add_relation("listOrders", "getOrder", "precedes")
    tg.add_relation("getOrder", "cancelOrder", "precedes")
    tg.add_relation("cancelOrder", "processRefund", "precedes")
    return tg


def _make_categorized_graph() -> ToolGraph:
    """Create a graph with domain/category/tool hierarchy."""
    tg = ToolGraph()
    tg.add_domain("ecommerce", "E-commerce platform")
    tg.add_category("orders", domain="ecommerce")
    tg.add_category("products", domain="ecommerce")
    for name in ["createOrder", "getOrder", "cancelOrder"]:
        tg.add_tool(ToolSchema(name=name, description=f"{name} desc", parameters=[]))
        tg.assign_category(name, "orders")
    for name in ["listProducts", "getProduct"]:
        tg.add_tool(ToolSchema(name=name, description=f"{name} desc", parameters=[]))
        tg.assign_category(name, "products")
    # Uncategorized
    tg.add_tool(ToolSchema(name="healthCheck", description="Health check", parameters=[]))
    return tg


class TestGetWorkflow:
    def test_full_chain(self):
        tg = _make_workflow_graph()
        api = tg.search_api
        chain = api.get_workflow("cancelOrder")
        assert chain == ["listOrders", "getOrder", "cancelOrder", "processRefund"]

    def test_chain_start(self):
        tg = _make_workflow_graph()
        api = tg.search_api
        chain = api.get_workflow("listOrders")
        assert chain == ["listOrders", "getOrder", "cancelOrder", "processRefund"]

    def test_chain_end(self):
        tg = _make_workflow_graph()
        api = tg.search_api
        chain = api.get_workflow("processRefund")
        assert chain == ["listOrders", "getOrder", "cancelOrder", "processRefund"]

    def test_nonexistent_tool(self):
        tg = _make_workflow_graph()
        api = tg.search_api
        assert api.get_workflow("noSuchTool") == []

    def test_isolated_tool(self):
        tg = ToolGraph()
        tg.add_tool(ToolSchema(name="standalone", description="Standalone", parameters=[]))
        chain = tg.search_api.get_workflow("standalone")
        assert chain == ["standalone"]


class TestBrowseCategories:
    def test_tree_structure(self):
        tg = _make_categorized_graph()
        tree = tg.search_api.browse_categories()
        assert "ecommerce" in tree["domains"]
        ecom = tree["domains"]["ecommerce"]
        assert "orders" in ecom["categories"]
        assert "products" in ecom["categories"]
        assert set(ecom["categories"]["orders"]["tools"]) == {
            "createOrder",
            "getOrder",
            "cancelOrder",
        }
        assert ecom["categories"]["orders"]["tool_count"] == 3

    def test_uncategorized(self):
        tg = _make_categorized_graph()
        tree = tg.search_api.browse_categories()
        assert "healthCheck" in tree["uncategorized"]

    def test_empty_graph(self):
        tg = ToolGraph()
        tree = tg.search_api.browse_categories()
        assert tree["domains"] == {}
        assert tree["uncategorized"] == []


class TestSearchTools:
    def test_returns_results(self):
        tg = _make_categorized_graph()
        results = tg.search_api.search_tools("create an order", top_k=3)
        assert len(results) > 0
        assert all("name" in r and "description" in r for r in results)

    def test_result_format(self):
        tg = _make_categorized_graph()
        results = tg.search_api.search_tools("list products", top_k=2)
        for r in results:
            assert "name" in r
            assert "description" in r
            assert "parameters" in r
            assert isinstance(r["parameters"], list)
