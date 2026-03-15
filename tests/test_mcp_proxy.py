"""Tests for MCP proxy module."""

from __future__ import annotations

import json

import pytest

from graph_tool_call.mcp_proxy import BackendConfig, MCPProxy, load_proxy_config

# --- Config loading ---


def test_load_proxy_config_native_format(tmp_path):
    config = {
        "backends": {
            "playwright": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-playwright"],
            },
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-filesystem", "/home"],
                "env": {"HOME": "/home"},
            },
        },
        "top_k": 10,
        "embedding": True,
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(config))

    backends, options = load_proxy_config(str(p))
    assert len(backends) == 2
    assert backends[0].name == "playwright"
    assert backends[0].command == "npx"
    assert backends[1].name == "filesystem"
    assert backends[1].env == {"HOME": "/home"}
    assert options["top_k"] == 10
    assert options["embedding"] is True


def test_load_proxy_config_mcp_json_format(tmp_path):
    config = {
        "mcpServers": {
            "my-server": {
                "command": "uvx",
                "args": ["some-package", "serve"],
            }
        }
    }
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps(config))

    backends, options = load_proxy_config(str(p))
    assert len(backends) == 1
    assert backends[0].name == "my-server"
    assert backends[0].command == "uvx"
    assert backends[0].args == ["some-package", "serve"]
    assert options == {}


def test_load_proxy_config_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"foo": "bar"}))

    with pytest.raises(ValueError, match="must have 'backends' or 'mcpServers'"):
        load_proxy_config(str(p))


# --- BackendConfig ---


def test_backend_config_defaults():
    cfg = BackendConfig(name="test", command="python")
    assert cfg.args == []
    assert cfg.env is None


def test_backend_config_full():
    cfg = BackendConfig(
        name="test",
        command="npx",
        args=["-y", "pkg"],
        env={"KEY": "val"},
    )
    assert cfg.name == "test"
    assert cfg.command == "npx"
    assert cfg.args == ["-y", "pkg"]
    assert cfg.env == {"KEY": "val"}


# --- MCPProxy unit tests (no real backends) ---


def test_proxy_init():
    backends = [BackendConfig(name="a", command="echo")]
    proxy = MCPProxy(backends, top_k=10)
    assert proxy.backend_count == 0
    assert proxy.all_tools == {}
    assert proxy.tool_to_backend == {}


def test_proxy_build_tool_graph_empty():
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    assert proxy.tool_graph is not None
    assert len(proxy.tool_graph.tools) == 0


def test_proxy_gateway_mode_determined_by_threshold():
    """Gateway mode activates when tools > threshold."""
    proxy = MCPProxy([], top_k=5, passthrough_threshold=2)
    proxy._build_tool_graph()
    # Manually add tools to simulate
    proxy._all_tools = {f"tool_{i}": None for i in range(10)}
    proxy._gateway_mode = len(proxy._all_tools) > proxy._passthrough_threshold
    assert proxy.is_gateway_mode is True

    proxy2 = MCPProxy([], top_k=5, passthrough_threshold=20)
    proxy2._build_tool_graph()
    proxy2._all_tools = {f"tool_{i}": None for i in range(10)}
    proxy2._gateway_mode = len(proxy2._all_tools) > proxy2._passthrough_threshold
    assert proxy2.is_gateway_mode is False


def test_proxy_search_returns_results():
    """search() returns tool info with descriptions."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    proxy._tg.add_tools(
        [
            {"name": "get_users", "description": "Get all users"},
            {"name": "create_user", "description": "Create a new user"},
            {"name": "delete_file", "description": "Delete a file"},
        ]
    )
    proxy._all_tools = {
        "get_users": None,
        "create_user": None,
        "delete_file": None,
    }

    results = proxy.search("user management", top_k=2)
    assert len(results) <= 2
    result_names = {r["name"] for r in results}
    assert result_names & {"get_users", "create_user"}


def test_proxy_search_zero_result_fallback():
    """search() returns suggestion when no matches found."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    proxy._all_tools = {"a": None}

    results = proxy.search("완전히 관련없는 검색어 xyz123")
    assert len(results) == 1
    assert "error" in results[0] or "suggestion" in results[0]


# --- create_proxy_server ---


def test_proxy_search_returns_scores():
    """search() returns score and confidence for each result."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    proxy._tg.add_tools(
        [
            {"name": "get_users", "description": "Get all users"},
            {"name": "create_user", "description": "Create a new user"},
        ]
    )
    proxy._all_tools = {"get_users": None, "create_user": None}

    results = proxy.search("get users")
    assert len(results) >= 1
    # Should have score and confidence fields (lightweight, no inputSchema)
    for r in results:
        if "error" not in r:
            assert "score" in r
            assert "confidence" in r
            assert "inputSchema" not in r


def test_proxy_search_updates_exposed_tools():
    """search() populates _exposed_tools for dynamic injection."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    proxy._tg.add_tools(
        [
            {"name": "get_users", "description": "Get all users"},
            {"name": "create_user", "description": "Create a new user"},
        ]
    )

    class FakeTool:
        description = "fake"
        inputSchema = {}  # noqa: N815

    proxy._all_tools = {"get_users": FakeTool(), "create_user": FakeTool()}

    assert len(proxy._exposed_tools) == 0
    proxy.search("user")
    # After search, exposed_tools should be populated
    assert len(proxy._exposed_tools) >= 1


def test_proxy_get_tool_schema():
    """get_tool_schema() returns full schema for known tool."""
    proxy = MCPProxy([], top_k=5)

    class FakeTool:
        description = "Fake tool description"
        inputSchema = {"type": "object", "properties": {"a": {"type": "string"}}}  # noqa: N815

    proxy._all_tools = {"my_tool": FakeTool()}
    schema = proxy.get_tool_schema("my_tool")
    assert schema is not None
    assert schema["name"] == "my_tool"
    assert "inputSchema" in schema

    # Unknown tool
    assert proxy.get_tool_schema("nonexistent") is None


@pytest.mark.asyncio
async def test_call_backend_tool_string_arguments():
    """call_backend_tool should handle arguments serialized as JSON string."""
    mcp_mod = pytest.importorskip("mcp", reason="mcp required")
    types = mcp_mod.types

    from graph_tool_call.mcp_proxy import create_proxy_server

    proxy = MCPProxy([], top_k=5, passthrough_threshold=0)
    proxy._build_tool_graph()
    proxy._all_tools = {"my_tool": None}
    proxy._tool_to_backend = {"my_tool": "backend1"}
    proxy._gateway_mode = True

    received_args = []

    # Mock the backend connection
    class FakeSession:
        async def call_tool(self, name, arguments):
            received_args.append(arguments)
            return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])

    class FakeConn:
        session = FakeSession()

    proxy._connections = {"backend1": FakeConn()}

    server = create_proxy_server(proxy)
    handler = server.request_handlers[types.CallToolRequest]

    # Case 1: arguments as JSON string (the bug this fix addresses)
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="call_backend_tool",
            arguments={"tool_name": "my_tool", "arguments": '{"action": "check"}'},
        ),
    )
    result = await handler(request)
    assert not result.root.isError
    assert received_args[-1] == {"action": "check"}

    # Case 2: arguments as None
    request2 = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="call_backend_tool",
            arguments={"tool_name": "my_tool", "arguments": None},
        ),
    )
    result2 = await handler(request2)
    assert not result2.root.isError
    assert received_args[-1] == {}

    # Case 3: arguments as proper dict (should still work)
    request3 = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="call_backend_tool",
            arguments={"tool_name": "my_tool", "arguments": {"action": "check"}},
        ),
    )
    result3 = await handler(request3)
    assert not result3.root.isError
    assert received_args[-1] == {"action": "check"}


def test_create_gateway_server():
    """Gateway mode creates server with meta-tools."""
    pytest.importorskip("mcp", reason="mcp required")

    from graph_tool_call.mcp_proxy import create_proxy_server

    proxy = MCPProxy([], top_k=5, passthrough_threshold=0)
    proxy._build_tool_graph()
    proxy._all_tools = {"a": None}
    proxy._gateway_mode = True
    server = create_proxy_server(proxy)
    assert server is not None


def test_create_passthrough_server():
    """Passthrough mode creates server that exposes all tools."""
    pytest.importorskip("mcp", reason="mcp required")

    from graph_tool_call.mcp_proxy import create_proxy_server

    proxy = MCPProxy([], top_k=5, passthrough_threshold=100)
    proxy._build_tool_graph()
    proxy._gateway_mode = False
    server = create_proxy_server(proxy)
    assert server is not None
