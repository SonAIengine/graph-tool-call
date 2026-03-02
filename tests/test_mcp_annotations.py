"""Test MCPAnnotations model serialization/deserialization."""

from graph_tool_call.core.tool import MCPAnnotations


def test_from_mcp_dict_full():
    data = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    ann = MCPAnnotations.from_mcp_dict(data)
    assert ann.read_only_hint is True
    assert ann.destructive_hint is False
    assert ann.idempotent_hint is True
    assert ann.open_world_hint is False


def test_from_mcp_dict_partial():
    data = {"readOnlyHint": True}
    ann = MCPAnnotations.from_mcp_dict(data)
    assert ann.read_only_hint is True
    assert ann.destructive_hint is None
    assert ann.idempotent_hint is None
    assert ann.open_world_hint is None


def test_from_mcp_dict_empty():
    ann = MCPAnnotations.from_mcp_dict({})
    assert ann.read_only_hint is None
    assert ann.destructive_hint is None


def test_to_mcp_dict_omits_none():
    ann = MCPAnnotations(read_only_hint=True, destructive_hint=False)
    d = ann.to_mcp_dict()
    assert d == {"readOnlyHint": True, "destructiveHint": False}
    assert "idempotentHint" not in d
    assert "openWorldHint" not in d


def test_to_mcp_dict_empty():
    ann = MCPAnnotations()
    assert ann.to_mcp_dict() == {}


def test_roundtrip():
    original = {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    ann = MCPAnnotations.from_mcp_dict(original)
    result = ann.to_mcp_dict()
    assert result == original


def test_annotations_in_tool_schema():
    from graph_tool_call.core.tool import ToolSchema

    ann = MCPAnnotations(read_only_hint=True, destructive_hint=False)
    tool = ToolSchema(name="test_tool", description="A test", annotations=ann)
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True


def test_tool_schema_annotations_none_by_default():
    from graph_tool_call.core.tool import ToolSchema

    tool = ToolSchema(name="test_tool")
    assert tool.annotations is None
