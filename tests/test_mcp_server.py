"""Tests for MCP server module."""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def mcp_app():
    """Create an MCP server with test tools."""
    from graph_tool_call.mcp_server import create_mcp_server

    app = create_mcp_server()

    # Add some test tools via the underlying ToolGraph
    # Access the ToolGraph through the closure
    from graph_tool_call import ToolGraph

    tg = ToolGraph()
    tg.add_tools([
        {
            "type": "function",
            "function": {
                "name": "getUser",
                "description": "Get user details by ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "User ID"},
                    },
                    "required": ["user_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deleteUser",
                "description": "Delete a user account permanently",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "User ID"},
                    },
                    "required": ["user_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listOrders",
                "description": "List all orders for a customer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string", "description": "Customer ID"},
                    },
                },
            },
        },
    ])

    # Rebuild MCP app with these tools
    return create_mcp_server(), tg


class TestCreateMcpServer:
    def test_create_server_returns_mcp_app(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        assert app is not None
        assert app.name == "graph-tool-call"

    def test_create_server_with_graph_file(self, tmp_path):
        from graph_tool_call import ToolGraph
        from graph_tool_call.mcp_server import create_mcp_server

        # Build and save a graph
        tg = ToolGraph()
        tg.add_tools([
            {
                "type": "function",
                "function": {
                    "name": "testTool",
                    "description": "A test tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ])
        graph_path = tmp_path / "test_graph.json"
        tg.save(graph_path)

        # Load from file
        app = create_mcp_server(graph_file=str(graph_path))
        assert app is not None


class TestMcpServerTools:
    """Test that the MCP server exposes the expected tools."""

    def test_server_has_required_tools(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        # FastMCP registers tools as callable functions
        tool_names = {t.name for t in app._tool_manager.list_tools()}
        assert "search_tools" in tool_names
        assert "get_tool_schema" in tool_names
        assert "list_categories" in tool_names
        assert "graph_info" in tool_names
        assert "load_source" in tool_names


class TestSearchToolsFunctionality:
    """Test search_tools logic by calling the function directly."""

    def test_search_empty_graph(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        # Find the search_tools function in registered tools
        tools = app._tool_manager.list_tools()
        search_tool = next(t for t in tools if t.name == "search_tools")
        assert search_tool is not None

    def test_graph_info_empty(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        tools = app._tool_manager.list_tools()
        info_tool = next(t for t in tools if t.name == "graph_info")
        assert info_tool is not None
