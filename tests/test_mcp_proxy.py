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
    assert proxy.active_filter is None
    assert proxy.all_tools == {}
    assert proxy.tool_to_backend == {}


def test_proxy_build_tool_graph_empty():
    """ToolGraph can be built with no tools."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    assert proxy.tool_graph is not None
    assert len(proxy.tool_graph.tools) == 0


def test_proxy_get_filtered_tool_names_no_filter():
    """Without active filter, all tools are returned."""
    proxy = MCPProxy([], top_k=5)
    proxy._all_tools = {"a": None, "b": None, "c": None}
    names = proxy.get_filtered_tool_names()
    assert set(names) == {"a", "b", "c"}


def test_proxy_get_filtered_tool_names_with_filter():
    """With active filter, only matching tools are returned."""
    proxy = MCPProxy([], top_k=5)
    proxy._all_tools = {"a": None, "b": None, "c": None}
    proxy._active_filter = {"a", "c"}
    names = proxy.get_filtered_tool_names()
    assert set(names) == {"a", "c"}


def test_proxy_search_updates_filter():
    """search() should update active_filter."""
    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()

    # Add some tools to ToolGraph manually
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
    assert proxy.active_filter is not None
    # At least one user-related tool should match
    result_names = {r["name"] for r in results}
    assert result_names & {"get_users", "create_user"}


# --- create_proxy_server ---


def test_create_proxy_server_requires_mcp():
    """create_proxy_server should work when mcp is installed."""
    pytest.importorskip("mcp", reason="mcp required")

    from graph_tool_call.mcp_proxy import create_proxy_server

    proxy = MCPProxy([], top_k=5)
    proxy._build_tool_graph()
    server = create_proxy_server(proxy)
    assert server is not None
