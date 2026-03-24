"""Tests for ToolGraph LangChain/LangGraph compatibility (as_tools / __iter__).

Verifies that ToolGraph can be used as a drop-in replacement for
``tools=[tool1, tool2]`` in LangChain/LangGraph agents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake LangChain tool stubs (same pattern as test_langchain_gateway.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeTool:
    """Minimal LangChain BaseTool stub with invoke() support."""

    name: str
    description: str
    args_schema: Any = None

    def invoke(self, input: Any) -> str:
        return f"{self.name} executed with {json.dumps(input, default=str)}"


@dataclass
class FakeArgsSchema:
    """Minimal Pydantic-like schema stub for parameter extraction."""

    _schema: dict = field(default_factory=dict)

    def model_json_schema(self) -> dict:
        return self._schema


def _make_math_tools() -> list[FakeTool]:
    """Create math tools matching the user's example."""
    add_schema = FakeArgsSchema(
        _schema={
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"},
            },
            "required": ["a", "b"],
        }
    )
    multiply_schema = FakeArgsSchema(
        _schema={
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"},
            },
            "required": ["a", "b"],
        }
    )
    return [
        FakeTool(name="add", description="Add two numbers together", args_schema=add_schema),
        FakeTool(
            name="multiply", description="Multiply two numbers", args_schema=multiply_schema
        ),
    ]


def _make_diverse_tools() -> list[FakeTool]:
    """Create a diverse set of tools for comprehensive testing."""
    specs = [
        ("add", "Add two numbers together"),
        ("multiply", "Multiply two numbers"),
        ("search_documents", "Search documents by query string"),
        ("get_weather", "Get current weather for a city"),
        ("send_email", "Send an email to a user"),
        ("create_user", "Create a new user account"),
        ("delete_user", "Delete a user account permanently"),
        ("get_order", "Get order details by order ID"),
        ("cancel_order", "Cancel an existing order"),
        ("process_refund", "Process a refund for a cancelled order"),
    ]
    return [FakeTool(name=n, description=d) for n, d in specs]


# ---------------------------------------------------------------------------
# as_tools() tests
# ---------------------------------------------------------------------------


class TestAsTools:
    """ToolGraph.as_tools() gateway creation."""

    def test_returns_two_tools(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        gateway = tg.as_tools()
        assert len(gateway) == 2

    def test_tool_names(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        gateway = tg.as_tools()
        names = {t.name for t in gateway}
        assert names == {"search_tools", "call_tool"}

    def test_tools_have_invoke(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        gateway = tg.as_tools()
        for t in gateway:
            assert hasattr(t, "invoke")
            assert hasattr(t, "name")
            assert hasattr(t, "description")

    def test_custom_top_k(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        gateway = tg.as_tools(top_k=3)
        search = next(t for t in gateway if t.name == "search_tools")

        result = json.loads(search.invoke({"query": "math operations"}))
        assert result["matched"] <= 3


# ---------------------------------------------------------------------------
# search_tools tests
# ---------------------------------------------------------------------------


class TestSearchTools:
    """search_tools gateway meta-tool behavior."""

    def _get_search_tool(self, tools, top_k=5):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in tools:
            tg.add_tool(t)

        gateway = tg.as_tools(top_k=top_k)
        return next(t for t in gateway if t.name == "search_tools")

    def test_search_returns_json(self):
        search = self._get_search_tool(_make_diverse_tools())

        result = search.invoke({"query": "add numbers"})
        data = json.loads(result)

        assert "tools" in data
        assert "matched" in data
        assert "total_tools" in data
        assert data["total_tools"] == 10

    def test_search_finds_relevant_tools(self):
        search = self._get_search_tool(_make_diverse_tools())

        result = search.invoke({"query": "cancel order"})
        data = json.loads(result)

        tool_names = [t["name"] for t in data["tools"]]
        assert "cancel_order" in tool_names

    def test_search_includes_parameters(self):
        search = self._get_search_tool(_make_math_tools())

        result = search.invoke({"query": "add"})
        data = json.loads(result)

        # Find the add tool in results
        add_results = [t for t in data["tools"] if t["name"] == "add"]
        assert len(add_results) == 1
        assert "parameters" in add_results[0]
        param_names = {p["name"] for p in add_results[0]["parameters"]}
        assert "a" in param_names
        assert "b" in param_names

    def test_search_respects_top_k_override(self):
        search = self._get_search_tool(_make_diverse_tools(), top_k=10)

        result = search.invoke({"query": "manage users", "top_k": 2})
        data = json.loads(result)

        assert data["matched"] <= 2

    def test_search_includes_hint(self):
        search = self._get_search_tool(_make_diverse_tools())

        result = search.invoke({"query": "weather"})
        data = json.loads(result)

        assert "hint" in data
        assert "call_tool" in data["hint"]


# ---------------------------------------------------------------------------
# call_tool tests
# ---------------------------------------------------------------------------


class TestCallTool:
    """call_tool gateway meta-tool behavior."""

    def _get_call_tool(self, tools):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in tools:
            tg.add_tool(t)

        gateway = tg.as_tools()
        return next(t for t in gateway if t.name == "call_tool")

    def test_call_existing_tool(self):
        call = self._get_call_tool(_make_diverse_tools())

        result = call.invoke({
            "tool_name": "cancel_order",
            "arguments": {"order_id": "123"},
        })

        assert "cancel_order" in result
        assert "123" in result

    def test_call_nonexistent_tool(self):
        call = self._get_call_tool(_make_diverse_tools())

        result = call.invoke({
            "tool_name": "nonexistent_tool",
            "arguments": {},
        })
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_call_with_none_arguments(self):
        call = self._get_call_tool(_make_diverse_tools())

        result = call.invoke({
            "tool_name": "get_weather",
            "arguments": None,
        })

        assert "get_weather" in result

    def test_call_with_missing_arguments(self):
        call = self._get_call_tool(_make_diverse_tools())

        result = call.invoke({
            "tool_name": "get_weather",
        })

        assert "get_weather" in result

    def test_call_returns_error_for_no_callable(self):
        """Tool registered without a callable (e.g., from OpenAPI spec) should error."""
        from graph_tool_call import ToolGraph
        from graph_tool_call.core.tool import ToolSchema

        tg = ToolGraph()
        # Add a tool without callable
        schema = ToolSchema(name="api_only", description="No callable")
        tg.add_tool(schema)

        gateway = tg.as_tools()
        call = next(t for t in gateway if t.name == "call_tool")

        result = call.invoke({"tool_name": "api_only"})
        data = json.loads(result)
        assert "error" in data
        assert "not callable" in data["error"].lower()


# ---------------------------------------------------------------------------
# __iter__ / __len__ (Sequence protocol) tests
# ---------------------------------------------------------------------------


class TestSequenceProtocol:
    """ToolGraph as iterable for LangChain tools parameter."""

    def test_len_is_two(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        assert len(tg) == 2

    def test_iter_yields_two_tools(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        tools = list(tg)
        assert len(tools) == 2

    def test_iter_tool_names(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        names = {t.name for t in tg}
        assert names == {"search_tools", "call_tool"}

    def test_iter_tools_have_invoke(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        for tool in tg:
            assert hasattr(tool, "invoke")

    def test_iter_is_idempotent(self):
        """Multiple iterations should return the same tools."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        tools_1 = list(tg)
        tools_2 = list(tg)
        assert tools_1[0] is tools_2[0]
        assert tools_1[1] is tools_2[1]

    def test_can_pass_to_list_constructor(self):
        """Verify list(tg) works (common in LangChain internals)."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        tools = list(tg)
        assert len(tools) == 2
        assert all(hasattr(t, "invoke") for t in tools)


# ---------------------------------------------------------------------------
# End-to-end workflow tests
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Full search → call workflow via ToolGraph gateway."""

    def test_search_then_call(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        gateway = tg.as_tools(top_k=5)
        search = next(t for t in gateway if t.name == "search_tools")
        call = next(t for t in gateway if t.name == "call_tool")

        # Step 1: Search
        search_result = json.loads(search.invoke({"query": "send email"}))
        assert any(t["name"] == "send_email" for t in search_result["tools"])

        # Step 2: Call
        call_result = call.invoke({
            "tool_name": "send_email",
            "arguments": {"to": "user@example.com", "body": "hello"},
        })
        assert "send_email" in call_result
        assert "executed" in call_result

    def test_search_then_call_via_iter(self):
        """Same workflow but using __iter__ (tools=tg pattern)."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        for t in _make_diverse_tools():
            tg.add_tool(t)

        tools = list(tg)  # simulates how create_react_agent consumes tools
        search = next(t for t in tools if t.name == "search_tools")
        call = next(t for t in tools if t.name == "call_tool")

        # Search and call
        search_result = json.loads(search.invoke({"query": "weather"}))
        assert any(t["name"] == "get_weather" for t in search_result["tools"])

        call_result = call.invoke({
            "tool_name": "get_weather",
            "arguments": {"city": "Seoul"},
        })
        assert "get_weather" in call_result

    def test_user_example_scenario(self):
        """Verify the exact scenario from the user's request."""
        from graph_tool_call import ToolGraph

        add = FakeTool(name="add", description="Add two numbers together")
        multiply = FakeTool(name="multiply", description="Multiply two numbers")
        search_documents = FakeTool(
            name="search_documents", description="Search documents by query string"
        )
        get_weather = FakeTool(
            name="get_weather", description="Get current weather for a city"
        )

        # ToolGraph creation and tool registration (user's pattern)
        tg_tool = ToolGraph()
        tg_tool.add_tool(add)
        tg_tool.add_tool(multiply)
        tg_tool.add_tool(search_documents)
        tg_tool.add_tool(get_weather)

        # Verify ToolGraph is usable as tools list
        tools = list(tg_tool)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"search_tools", "call_tool"}

        # Verify search works
        search = next(t for t in tools if t.name == "search_tools")
        result = json.loads(search.invoke({"query": "add numbers"}))
        assert result["total_tools"] == 4
        tool_names = [t["name"] for t in result["tools"]]
        assert "add" in tool_names

        # Verify call works
        call = next(t for t in tools if t.name == "call_tool")
        call_result = call.invoke({
            "tool_name": "add",
            "arguments": {"a": 1, "b": 2},
        })
        assert "add" in call_result
        assert "executed" in call_result

    def test_add_tool_after_gateway_creation(self):
        """Tools added after as_tools() should be visible (live reference)."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(FakeTool(name="add", description="Add two numbers"))

        gateway = tg.as_tools()
        search = next(t for t in gateway if t.name == "search_tools")
        call = next(t for t in gateway if t.name == "call_tool")

        # Initially 1 tool
        result = json.loads(search.invoke({"query": "all"}))
        assert result["total_tools"] == 1

        # Add another tool
        tg.add_tool(FakeTool(name="multiply", description="Multiply two numbers"))

        # Now 2 tools visible through the same gateway
        result = json.loads(search.invoke({"query": "all"}))
        assert result["total_tools"] == 2

        # And the new tool is callable
        call_result = call.invoke({
            "tool_name": "multiply",
            "arguments": {"a": 3, "b": 4},
        })
        assert "multiply" in call_result

    def test_add_tools_batch(self):
        """add_tools() batch registration should work with gateway."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tools = _make_diverse_tools()
        tg.add_tools(tools, detect_dependencies=False)

        gateway = tg.as_tools(top_k=5)
        search = next(t for t in gateway if t.name == "search_tools")

        result = json.loads(search.invoke({"query": "cancel order"}))
        assert result["total_tools"] == 10
        tool_names = [t["name"] for t in result["tools"]]
        assert "cancel_order" in tool_names


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_graph_search(self):
        """Search on empty graph should return empty results."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        gateway = tg.as_tools()
        search = next(t for t in gateway if t.name == "search_tools")

        result = json.loads(search.invoke({"query": "anything"}))
        assert result["matched"] == 0
        assert result["total_tools"] == 0

    def test_empty_graph_call(self):
        """Calling on empty graph should return error."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        gateway = tg.as_tools()
        call = next(t for t in gateway if t.name == "call_tool")

        result = call.invoke({"tool_name": "nonexistent"})
        data = json.loads(result)
        assert "error" in data

    def test_call_with_dict_arguments(self):
        """call_tool should handle dict arguments."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(FakeTool(name="add", description="Add numbers"))

        gateway = tg.as_tools()
        call = next(t for t in gateway if t.name == "call_tool")

        result = call.invoke({
            "tool_name": "add",
            "arguments": {"a": 1, "b": 2},
        })
        assert "add" in result
        assert "executed" in result

    def test_repr_unchanged(self):
        """__repr__ should still show tool count (not gateway tools)."""
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(FakeTool(name="add", description="Add"))
        tg.add_tool(FakeTool(name="multiply", description="Multiply"))

        r = repr(tg)
        assert "tools=2" in r
