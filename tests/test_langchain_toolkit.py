"""Tests for graph_tool_call.langchain.toolkit (filter_tools / GraphToolkit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeTool:
    """Minimal LangChain BaseTool stub for testing."""

    name: str
    description: str
    args_schema: Any = None

    def invoke(self, input: Any) -> str:
        return f"{self.name} called"


def _make_tools(n: int = 10) -> list[FakeTool]:
    names = [
        ("search_users", "Search for users by name or email"),
        ("create_user", "Create a new user account"),
        ("delete_user", "Delete a user account permanently"),
        ("get_order", "Get order details by order ID"),
        ("cancel_order", "Cancel an existing order"),
        ("process_refund", "Process a refund for a cancelled order"),
        ("send_email", "Send an email to a user"),
        ("get_weather", "Get current weather for a city"),
        ("calculate", "Perform mathematical calculations"),
        ("read_file", "Read contents of a file"),
    ]
    return [FakeTool(name=name, description=desc) for name, desc in names[:n]]


def test_filter_tools_returns_subset():
    from graph_tool_call import filter_tools

    tools = _make_tools()
    filtered = filter_tools(tools, "cancel my order", top_k=3)

    assert len(filtered) <= 3
    assert all(isinstance(t, FakeTool) for t in filtered)
    # cancel_order should be in results
    names = [t.name for t in filtered]
    assert "cancel_order" in names


def test_filter_tools_preserves_original_objects():
    from graph_tool_call import filter_tools

    tools = _make_tools()
    filtered = filter_tools(tools, "send email", top_k=3)

    # Returned tools should be the same objects, not copies
    for t in filtered:
        assert t in tools


def test_filter_tools_with_prebuilt_graph():
    from graph_tool_call import ToolGraph
    from graph_tool_call import filter_tools

    tools = _make_tools()
    tg = ToolGraph()

    filtered = filter_tools(tools, "delete user", top_k=3, graph=tg)
    assert len(filtered) <= 3
    # Graph should have been populated
    assert len(tg.tools) > 0


def test_filter_tools_returns_all_on_no_match():
    from graph_tool_call import filter_tools

    tools = _make_tools(2)
    # With only 2 tools, retrieval should still return something
    filtered = filter_tools(tools, "xyzzy nonexistent query", top_k=5)
    assert len(filtered) > 0


def test_toolkit_get_tools():
    from graph_tool_call import GraphToolkit

    tools = _make_tools()
    toolkit = GraphToolkit(tools=tools, top_k=3)

    filtered = toolkit.get_tools("search for users")
    assert len(filtered) <= 3
    names = [t.name for t in filtered]
    assert "search_users" in names


def test_toolkit_get_tools_override_top_k():
    from graph_tool_call import GraphToolkit

    tools = _make_tools()
    toolkit = GraphToolkit(tools=tools, top_k=2)

    filtered = toolkit.get_tools("order", top_k=5)
    assert len(filtered) <= 5


def test_toolkit_all_tools():
    from graph_tool_call import GraphToolkit

    tools = _make_tools(5)
    toolkit = GraphToolkit(tools=tools)

    assert len(toolkit.all_tools) == 5


def test_toolkit_graph_accessible():
    from graph_tool_call import ToolGraph
    from graph_tool_call import GraphToolkit

    tools = _make_tools()
    toolkit = GraphToolkit(tools=tools)

    assert isinstance(toolkit.graph, ToolGraph)
    assert len(toolkit.graph.tools) == len(tools)


def test_toolkit_with_prebuilt_graph():
    from graph_tool_call import ToolGraph
    from graph_tool_call import GraphToolkit

    tg = ToolGraph()
    tools = _make_tools(5)
    toolkit = GraphToolkit(tools=tools, graph=tg)

    # Should use the provided graph
    assert toolkit.graph is tg


def test_filter_openai_function_dicts():
    """OpenAI function-calling format dicts should work."""
    from graph_tool_call import filter_tools

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Send an email to a recipient",
                "parameters": {
                    "type": "object",
                    "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_docs",
                "description": "Search documents by keyword",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
    ]
    filtered = filter_tools(tools, "weather forecast", top_k=2)
    assert len(filtered) <= 2
    names = [t["function"]["name"] for t in filtered]
    assert "get_weather" in names
    # Original dicts preserved
    assert all(isinstance(t, dict) for t in filtered)


def test_filter_mcp_tool_dicts():
    """MCP tool format dicts should work."""
    from graph_tool_call import filter_tools

    tools = [
        {
            "name": "read_file",
            "description": "Read a file from disk",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
        {
            "name": "write_file",
            "description": "Write content to a file",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            },
        },
        {
            "name": "delete_file",
            "description": "Delete a file permanently",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    ]
    filtered = filter_tools(tools, "read file contents", top_k=2)
    assert len(filtered) <= 2
    names = [t["name"] for t in filtered]
    assert "read_file" in names


def test_filter_python_callables():
    """Plain Python functions should work."""
    from graph_tool_call import filter_tools

    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return f"sunny in {city}"

    def send_email(to: str, body: str) -> None:
        """Send an email to a recipient."""

    def calculate(expression: str) -> float:
        """Evaluate a math expression."""
        return 0.0

    tools = [get_weather, send_email, calculate]
    filtered = filter_tools(tools, "what is the weather", top_k=2)
    assert len(filtered) <= 2
    names = [t.__name__ for t in filtered]
    assert "get_weather" in names
    assert all(callable(t) for t in filtered)


def test_toolkit_with_openai_dicts():
    """GraphToolkit should accept OpenAI dicts."""
    from graph_tool_call import GraphToolkit

    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_users",
                "description": "List all users",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_user",
                "description": "Create a new user",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        },
    ]
    toolkit = GraphToolkit(tools=tools, top_k=2)
    assert len(toolkit.all_tools) == 2
    assert len(toolkit.graph.tools) == 2

    filtered = toolkit.get_tools("create a user")
    assert len(filtered) >= 1


def test_top_level_import():
    """filter_tools and GraphToolkit should be importable from top-level package."""
    from graph_tool_call import GraphToolkit, filter_tools

    assert callable(filter_tools)
    assert callable(GraphToolkit)


def test_langchain_compat_import():
    """Backward compat: still importable from graph_tool_call.langchain."""
    from graph_tool_call.langchain import GraphToolkit, filter_tools

    assert callable(filter_tools)
    assert callable(GraphToolkit)
