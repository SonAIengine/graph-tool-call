"""Test MCP tool ingest + parse_tool() auto-detection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from graph_tool_call import (
    MCPToolCatalog,
    MCPToolsIngestAdapter,
)
from graph_tool_call import (
    extract_mcp_tool_catalog as public_extract_mcp_tool_catalog,
)
from graph_tool_call.core.tool import ToolSchema, parse_mcp_tool, parse_tool
from graph_tool_call.ingest.mcp import (
    extract_mcp_tool_catalog,
    fetch_mcp_tools,
    ingest_mcp_tools,
)


def _make_mcp_tool(name="read_file", desc="Read a file", annotations=None):
    tool = {
        "name": name,
        "description": desc,
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
    }
    if annotations:
        tool["annotations"] = annotations
    return tool


def test_parse_mcp_tool_basic():
    tool_dict = _make_mcp_tool()
    schema = parse_mcp_tool(tool_dict)
    assert schema.name == "read_file"
    assert schema.description == "Read a file"
    assert len(schema.parameters) == 1
    assert schema.parameters[0].name == "path"
    assert schema.parameters[0].required is True
    assert schema.annotations is None


def test_parse_mcp_tool_with_annotations():
    tool_dict = _make_mcp_tool(
        annotations={
            "title": "Read workspace file",
            "readOnlyHint": True,
            "destructiveHint": False,
        }
    )
    schema = parse_mcp_tool(tool_dict)
    assert schema.annotations is not None
    assert schema.annotations.title == "Read workspace file"
    assert schema.annotations.read_only_hint is True
    assert schema.annotations.destructive_hint is False
    assert schema.annotations.idempotent_hint is None


def test_parse_tool_auto_detects_mcp():
    """parse_tool() should detect inputSchema and use MCP parser."""
    tool_dict = _make_mcp_tool(annotations={"readOnlyHint": True})
    schema = parse_tool(tool_dict)
    assert isinstance(schema, ToolSchema)
    assert schema.annotations is not None
    assert schema.annotations.read_only_hint is True


def test_parse_tool_still_detects_anthropic():
    """Anthropic format (input_schema) should still work."""
    tool_dict = {
        "name": "test",
        "description": "test",
        "input_schema": {"type": "object", "properties": {}},
    }
    schema = parse_tool(tool_dict)
    assert schema.name == "test"


def test_ingest_mcp_tools_basic():
    tools = [
        _make_mcp_tool("read_file", "Read a file"),
        _make_mcp_tool("write_file", "Write a file"),
    ]
    result = ingest_mcp_tools(tools)
    assert len(result) == 2
    assert result[0].name == "read_file"
    assert result[1].name == "write_file"


def test_ingest_mcp_tools_with_server_name():
    tools = [_make_mcp_tool("read_file")]
    result = ingest_mcp_tools(tools, server_name="filesystem")
    assert result[0].metadata.get("mcp_server") == "filesystem"
    assert "filesystem" in result[0].tags


def test_ingest_mcp_tools_preserves_annotations():
    tools = [
        _make_mcp_tool("delete_file", annotations={"destructiveHint": True}),
    ]
    result = ingest_mcp_tools(tools)
    assert result[0].annotations is not None
    assert result[0].annotations.destructive_hint is True


def test_parse_mcp_tool_preserves_latest_contract_and_builds_io_evidence():
    tool_dict = {
        "name": "lookup_customer",
        "title": "Customer lookup",
        "description": "Look up one customer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customerId": {"type": "string", "description": "Customer identifier"},
                "includeOrders": {"type": "boolean"},
            },
            "required": ["customerId"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "displayName": {"type": "string"},
                    },
                    "required": ["id"],
                }
            },
            "required": ["customer"],
        },
        "annotations": {
            "title": "Lookup customer",
            "readOnlyHint": True,
            "destructiveHint": False,
        },
        "execution": {"taskSupport": "optional"},
        "icons": [{"src": "data:image/png;base64,not-persisted"}],
        "_meta": {"authorization": "not-persisted"},
    }

    schema = parse_mcp_tool(tool_dict)

    assert schema.name == "lookup_customer"
    assert schema.metadata["mcp"]["title"] == "Customer lookup"
    assert schema.metadata["mcp"]["display_title"] == "Customer lookup"
    assert schema.metadata["mcp"]["execution"] == {"taskSupport": "optional"}
    assert "icons" not in schema.metadata["mcp"]
    assert "_meta" not in schema.metadata["mcp"]
    assert schema.metadata["request_body_schema"] == tool_dict["inputSchema"]
    assert schema.metadata["response_schema"] == tool_dict["outputSchema"]
    assert {row["field_name"] for row in schema.metadata["api_contract"]["consumes"]} == {
        "customerId",
        "includeOrders",
    }
    assert {row["field_name"] for row in schema.metadata["api_contract"]["produces"]} >= {
        "id",
        "displayName",
    }


def test_parse_mcp_tool_detaches_canonical_schemas_from_source():
    tool_dict = {
        "name": "lookup_customer",
        "inputSchema": {
            "type": "object",
            "properties": {"customerId": {"type": "string", "enum": ["one"]}},
        },
        "outputSchema": {
            "type": "object",
            "properties": {"displayName": {"type": "string"}},
        },
    }

    schema = parse_mcp_tool(tool_dict)
    tool_dict["inputSchema"]["properties"]["customerId"]["enum"].append("two")
    tool_dict["outputSchema"]["properties"]["displayName"]["type"] = "integer"

    assert schema.parameters[0].enum == ["one"]
    assert schema.metadata["request_body_schema"]["properties"]["customerId"]["enum"] == ["one"]
    assert schema.metadata["response_schema"]["properties"]["displayName"]["type"] == "string"


def test_extract_mcp_tool_catalog_accepts_jsonrpc_tools_list_page():
    catalog = extract_mcp_tool_catalog(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [_make_mcp_tool("read_file")],
                "nextCursor": "page-2",
                "serverInfo": {"name": "filesystem", "version": "2.0.0"},
            },
        }
    )

    assert [tool["name"] for tool in catalog.tools] == ["read_file"]
    assert catalog.server_name == "filesystem"
    assert catalog.server_version == "2.0.0"
    assert catalog.next_cursor == "page-2"


def test_mcp_catalog_contract_is_public():
    catalog = public_extract_mcp_tool_catalog({"tools": [_make_mcp_tool()]})

    assert isinstance(catalog, MCPToolCatalog)
    assert MCPToolsIngestAdapter.name == "mcp-tools"


def test_tool_graph_ingest_mcp_tools():
    from graph_tool_call import ToolGraph

    tg = ToolGraph()
    tools = [
        _make_mcp_tool("read_file", "Read a file", annotations={"readOnlyHint": True}),
        _make_mcp_tool("write_file", "Write a file", annotations={"readOnlyHint": False}),
    ]
    result = tg.ingest_mcp_tools(tools, server_name="fs")
    assert len(result) == 2
    assert "read_file" in tg.tools
    assert "write_file" in tg.tools
    assert tg.tools["read_file"].annotations.read_only_hint is True


def test_parse_mcp_tool_no_properties():
    """MCP tool with empty inputSchema should still parse."""
    tool_dict = {
        "name": "ping",
        "description": "Ping server",
        "inputSchema": {"type": "object"},
    }
    schema = parse_mcp_tool(tool_dict)
    assert schema.name == "ping"
    assert len(schema.parameters) == 0


def test_parse_mcp_tool_enum_params():
    tool_dict = {
        "name": "set_mode",
        "description": "Set mode",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "Operating mode",
                    "enum": ["fast", "slow"],
                },
            },
        },
    }
    schema = parse_mcp_tool(tool_dict)
    assert schema.parameters[0].enum == ["fast", "slow"]


def test_fetch_mcp_tools_jsonrpc_result():
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [_make_mcp_tool("read_file")],
            "serverInfo": {"name": "filesystem"},
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        tools, server_name = fetch_mcp_tools("https://mcp.example.com/mcp")

    assert len(tools) == 1
    assert tools[0]["name"] == "read_file"
    assert server_name == "filesystem"


def test_fetch_mcp_tools_falls_back_to_hostname():
    response = {"tools": [_make_mcp_tool("read_file")]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        _, server_name = fetch_mcp_tools("https://mcp.example.com/mcp")

    assert server_name == "mcp.example.com"


def test_fetch_mcp_tools_rejects_paginated_catalog_by_default():
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [_make_mcp_tool("read_file")],
            "nextCursor": "page-2",
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        try:
            fetch_mcp_tools("https://mcp.example.com/mcp")
        except ValueError as exc:
            assert "paginated" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_fetch_mcp_tools_allows_explicit_partial_preview():
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [_make_mcp_tool("read_file")],
            "nextCursor": "page-2",
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        tools, _ = fetch_mcp_tools(
            "https://mcp.example.com/mcp",
            allow_partial_catalog=True,
        )

    assert [tool["name"] for tool in tools] == ["read_file"]


def test_fetch_mcp_tools_error_response():
    response = {"jsonrpc": "2.0", "id": 1, "error": {"message": "unauthorized"}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        try:
            fetch_mcp_tools("https://mcp.example.com/mcp")
        except ValueError as e:
            assert "unauthorized" in str(e)
        else:
            raise AssertionError("expected ValueError")


def test_fetch_mcp_tools_blocks_private_host_by_default():
    with patch("graph_tool_call.net._open_url") as mock_open:
        try:
            fetch_mcp_tools("http://127.0.0.1:3000/mcp")
        except ConnectionError as e:
            assert "private or local host" in str(e)
        else:
            raise AssertionError("expected ConnectionError")
    mock_open.assert_not_called()


def test_tool_graph_ingest_mcp_server():
    from graph_tool_call import ToolGraph

    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                _make_mcp_tool("read_file", annotations={"readOnlyHint": True}),
                _make_mcp_tool("write_file", annotations={"readOnlyHint": False}),
            ],
            "serverInfo": {"name": "filesystem"},
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        tg = ToolGraph()
        result = tg.ingest_mcp_server("https://mcp.example.com/mcp")

    assert len(result) == 2
    assert "read_file" in tg.tools
    assert tg.tools["read_file"].metadata["mcp_server"] == "filesystem"
    assert tg.tools["read_file"].annotations.read_only_hint is True


def test_tool_graph_ingest_mcp_server_allows_private_host_with_opt_in():
    from graph_tool_call import ToolGraph

    response = {"tools": [_make_mcp_tool("read_file")]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "http://127.0.0.1:3000/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        tg = ToolGraph()
        result = tg.ingest_mcp_server(
            "http://127.0.0.1:3000/mcp",
            allow_private_hosts=True,
        )

    assert len(result) == 1
    assert "read_file" in tg.tools


def test_tool_graph_ingest_mcp_server_requires_explicit_partial_preview():
    from graph_tool_call import ToolGraph

    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [_make_mcp_tool("read_file")],
            "nextCursor": "page-2",
        },
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response).encode()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.geturl.return_value = "https://mcp.example.com/mcp"
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("graph_tool_call.net._open_url", return_value=mock_resp):
        graph = ToolGraph()
        result = graph.ingest_mcp_server(
            "https://mcp.example.com/mcp",
            allow_partial_catalog=True,
        )

    assert [tool.name for tool in result] == ["read_file"]
