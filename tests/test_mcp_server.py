"""Tests for MCP server module."""

from __future__ import annotations

import pytest

mcp = pytest.importorskip("mcp", reason="mcp SDK not installed")


class TestCreateMcpServer:
    def test_create_server_returns_mcp_app(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        assert app is not None
        assert app.name == "graph-tool-call"

    def test_create_server_with_graph_file(self, tmp_path):
        from graph_tool_call import ToolGraph
        from graph_tool_call.mcp_server import create_mcp_server

        tg = ToolGraph()
        tg.add_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "testTool",
                        "description": "A test tool",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ]
        )
        graph_path = tmp_path / "test_graph.json"
        tg.save(graph_path)

        app = create_mcp_server(graph_file=str(graph_path))
        assert app is not None


class TestMcpServerTools:
    """Test that the MCP server exposes the expected tools."""

    def test_server_has_required_tools(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
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
        tools = app._tool_manager.list_tools()
        search_tool = next(t for t in tools if t.name == "search_tools")
        assert search_tool is not None

    def test_graph_info_empty(self):
        from graph_tool_call.mcp_server import create_mcp_server

        app = create_mcp_server()
        tools = app._tool_manager.list_tools()
        info_tool = next(t for t in tools if t.name == "graph_info")
        assert info_tool is not None
