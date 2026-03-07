"""Tests for commerce domain preset."""

from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.presets.commerce import detect_commerce_patterns, is_commerce_api


def _tool(name: str, desc: str = "", path: str = "") -> ToolSchema:
    metadata = {}
    if path:
        metadata["path"] = path
    return ToolSchema(name=name, description=desc, parameters=[], metadata=metadata)


class TestCommerceDetection:
    def test_is_commerce_api(self):
        tools = [
            _tool("createOrder", "Create a new order", "/orders"),
            _tool("processPayment", "Process payment", "/payments"),
            _tool("createShipment", "Create shipment", "/shipments"),
            _tool("getUser", "Get user", "/users"),
        ]
        assert is_commerce_api(tools) is True

    def test_not_commerce_api(self):
        tools = [
            _tool("getUser", "Get user"),
            _tool("listFiles", "List files"),
            _tool("sendEmail", "Send email"),
        ]
        assert is_commerce_api(tools) is False

    def test_detect_order_payment_shipping_chain(self):
        tools = [
            _tool("createOrder", "Create a new order", "/orders"),
            _tool("processPayment", "Process payment", "/payments"),
            _tool("createShipment", "Create shipment", "/shipments"),
        ]
        relations = detect_commerce_patterns(tools)
        assert len(relations) >= 1
        # order -> payment should be detected
        pair_found = False
        for r in relations:
            if (
                "Order" in r.source
                and "Payment" in r.source
                or (r.source == "createOrder" and r.target == "processPayment")
            ):
                pair_found = True
                break
        assert pair_found

    def test_cart_to_order(self):
        tools = [
            _tool("addToCart", "Add item to cart", "/cart/items"),
            _tool("placeOrder", "Place an order", "/orders"),
        ]
        relations = detect_commerce_patterns(tools)
        assert len(relations) >= 1
        assert relations[0].source == "addToCart"
        assert relations[0].target == "placeOrder"

    def test_return_to_refund(self):
        tools = [
            _tool("createReturn", "Create a return request", "/returns"),
            _tool("processRefund", "Process refund", "/refunds"),
        ]
        relations = detect_commerce_patterns(tools)
        assert len(relations) >= 1


class TestApplyCommercePreset:
    def test_apply_adds_relations(self):
        tg = ToolGraph()
        for t in [
            _tool("createOrder", "Create order", "/orders"),
            _tool("processPayment", "Process payment", "/payments"),
            _tool("createShipment", "Create shipment", "/shipments"),
        ]:
            tg.add_tool(t)
        added = tg.apply_commerce_preset()
        assert added >= 1
        assert tg.graph.edge_count() >= 1

    def test_no_duplicate_on_reapply(self):
        tg = ToolGraph()
        for t in [
            _tool("createOrder", "Create order", "/orders"),
            _tool("processPayment", "Process payment", "/payments"),
        ]:
            tg.add_tool(t)
        added1 = tg.apply_commerce_preset()
        added2 = tg.apply_commerce_preset()
        assert added1 >= 1
        assert added2 == 0


class TestProgressiveDisclosure:
    def test_standalone_html_export(self):
        import tempfile
        from pathlib import Path

        tg = ToolGraph()
        tg.add_tool(ToolSchema(name="test_tool", description="Test", parameters=[]))
        tg.add_category("test_cat")
        tg.assign_category("test_tool", "test_cat")

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.html"
            tg.export_html(out, standalone=True)
            assert out.exists()
            content = out.read_text()
            assert "vis-network" in content
            assert "test_tool" in content

    def test_progressive_disclosure_html(self):
        import tempfile
        from pathlib import Path

        tg = ToolGraph()
        tg.add_tool(ToolSchema(name="tool_a", description="Tool A", parameters=[]))
        tg.add_tool(ToolSchema(name="tool_b", description="Tool B", parameters=[]))
        tg.add_category("cat1")
        tg.assign_category("tool_a", "cat1")
        tg.assign_category("tool_b", "cat1")

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "graph.html"
            tg.export_html(out, progressive=True)
            assert out.exists()
            content = out.read_text()
            assert "doubleClick" in content
            assert '"hidden": true' in content or '"hidden":true' in content
