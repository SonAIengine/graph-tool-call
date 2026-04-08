"""Tests for graph_tool_call.langchain.gateway (create_gateway_tools)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class FakeTool:
    """Minimal LangChain BaseTool stub."""

    name: str
    description: str
    args_schema: Any = None

    def invoke(self, input: Any) -> str:
        return f"{self.name} executed with {json.dumps(input)}"


def _make_tools() -> list[FakeTool]:
    specs = [
        ("search_users", "Search for users by name or email"),
        ("create_user", "Create a new user account"),
        ("delete_user", "Delete a user account permanently"),
        ("get_order", "Get order details by order ID"),
        ("cancel_order", "Cancel an existing order"),
        ("process_refund", "Process a refund for a cancelled order"),
        ("send_email", "Send an email to a user"),
        ("get_weather", "Get current weather for a city"),
        ("list_products", "List all products in the catalog"),
        ("update_inventory", "Update product inventory count"),
    ]
    return [FakeTool(name=n, description=d) for n, d in specs]


class TestCreateGatewayTools:
    """create_gateway_tools basic behavior."""

    def test_returns_two_tools(self):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        tools = _make_tools()
        gateway = create_gateway_tools(tools)

        assert len(gateway) == 2

    def test_tool_names(self):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        tools = _make_tools()
        gateway = create_gateway_tools(tools)

        names = {t.name for t in gateway}
        assert names == {"search_tools", "call_tool"}

    def test_tools_are_langchain_tools(self):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        tools = _make_tools()
        gateway = create_gateway_tools(tools)

        for t in gateway:
            assert hasattr(t, "invoke")
            assert hasattr(t, "name")
            assert hasattr(t, "description")


class TestSearchTools:
    """search_tools meta-tool behavior."""

    def _get_search_tool(self, tools):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        gateway = create_gateway_tools(tools, top_k=5)
        return next(t for t in gateway if t.name == "search_tools")

    def test_search_returns_json(self):
        tools = _make_tools()
        search = self._get_search_tool(tools)

        result = search.invoke({"query": "cancel order"})
        data = json.loads(result)

        assert "tools" in data
        assert "matched" in data
        assert "total_tools" in data
        assert data["total_tools"] == 10

    def test_search_finds_relevant_tools(self):
        tools = _make_tools()
        search = self._get_search_tool(tools)

        result = search.invoke({"query": "cancel order"})
        data = json.loads(result)

        tool_names = [t["name"] for t in data["tools"]]
        assert "cancel_order" in tool_names

    def test_search_respects_top_k(self):
        tools = _make_tools()
        search = self._get_search_tool(tools)

        result = search.invoke({"query": "user management", "top_k": 3})
        data = json.loads(result)

        assert data["matched"] <= 3

    def test_search_returns_descriptions(self):
        tools = _make_tools()
        search = self._get_search_tool(tools)

        result = search.invoke({"query": "email"})
        data = json.loads(result)

        for t in data["tools"]:
            assert "name" in t
            assert "description" in t


class TestCallTool:
    """call_tool meta-tool behavior."""

    def _get_call_tool(self, tools):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        gateway = create_gateway_tools(tools)
        return next(t for t in gateway if t.name == "call_tool")

    def test_call_existing_tool(self):
        tools = _make_tools()
        call = self._get_call_tool(tools)

        result = call.invoke(
            {
                "tool_name": "cancel_order",
                "arguments": {"order_id": "123"},
            }
        )

        assert "cancel_order" in result
        assert "123" in result

    def test_call_nonexistent_tool(self):
        tools = _make_tools()
        call = self._get_call_tool(tools)

        result = call.invoke(
            {
                "tool_name": "nonexistent_tool",
                "arguments": {},
            }
        )
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_call_with_empty_arguments(self):
        tools = _make_tools()
        call = self._get_call_tool(tools)

        result = call.invoke(
            {
                "tool_name": "get_weather",
            }
        )

        assert "get_weather" in result

    def test_call_with_none_arguments(self):
        tools = _make_tools()
        call = self._get_call_tool(tools)

        result = call.invoke(
            {
                "tool_name": "get_weather",
                "arguments": None,
            }
        )

        assert "get_weather" in result


class TestEndToEnd:
    """Full search → call workflow."""

    def test_search_then_call(self):
        from graph_tool_call.langchain.gateway import create_gateway_tools

        tools = _make_tools()
        gateway = create_gateway_tools(tools, top_k=5)

        search = next(t for t in gateway if t.name == "search_tools")
        call = next(t for t in gateway if t.name == "call_tool")

        # Step 1: Search
        search_result = json.loads(search.invoke({"query": "send email"}))
        assert any(t["name"] == "send_email" for t in search_result["tools"])

        # Step 2: Call
        call_result = call.invoke(
            {
                "tool_name": "send_email",
                "arguments": {"to": "user@example.com", "body": "hello"},
            }
        )
        assert "send_email" in call_result
        assert "executed" in call_result

    def test_import_from_top_level(self):
        """Verify create_gateway_tools is importable from top-level."""
        from graph_tool_call import create_gateway_tools

        assert callable(create_gateway_tools)

    def test_import_from_langchain(self):
        """Verify create_gateway_tools is importable from langchain subpackage."""
        from graph_tool_call.langchain import create_gateway_tools

        assert callable(create_gateway_tools)
