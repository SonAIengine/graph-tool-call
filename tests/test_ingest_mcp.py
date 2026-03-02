"""Test MCP tool ingest + parse_tool() auto-detection."""

from graph_tool_call.core.tool import ToolSchema, parse_mcp_tool, parse_tool
from graph_tool_call.ingest.mcp import ingest_mcp_tools


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
    tool_dict = _make_mcp_tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    schema = parse_mcp_tool(tool_dict)
    assert schema.annotations is not None
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
