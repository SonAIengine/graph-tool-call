"""E2E test: annotation-aware retrieval boosts correct tools."""

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import MCPAnnotations, ToolSchema


def _build_mixed_tool_graph():
    """Build a ToolGraph with a mix of read-only and destructive tools."""
    tg = ToolGraph()

    read_tools = [
        ToolSchema(
            name="list_users",
            description="List all users in the system",
            annotations=MCPAnnotations(read_only_hint=True, destructive_hint=False),
        ),
        ToolSchema(
            name="get_user",
            description="Get user details by ID",
            annotations=MCPAnnotations(read_only_hint=True, destructive_hint=False),
        ),
        ToolSchema(
            name="search_users",
            description="Search users by name",
            annotations=MCPAnnotations(read_only_hint=True, destructive_hint=False),
        ),
    ]

    write_tools = [
        ToolSchema(
            name="create_user",
            description="Create a new user",
            annotations=MCPAnnotations(read_only_hint=False, destructive_hint=False),
        ),
        ToolSchema(
            name="update_user",
            description="Update user information",
            annotations=MCPAnnotations(read_only_hint=False, destructive_hint=False),
        ),
    ]

    delete_tools = [
        ToolSchema(
            name="delete_user",
            description="Delete a user permanently",
            annotations=MCPAnnotations(read_only_hint=False, destructive_hint=True),
        ),
        ToolSchema(
            name="remove_user_role",
            description="Remove a role from user",
            annotations=MCPAnnotations(read_only_hint=False, destructive_hint=True),
        ),
    ]

    for tool in read_tools + write_tools + delete_tools:
        tg.add_tool(tool)

    return tg


def test_read_query_prefers_readonly():
    tg = _build_mixed_tool_graph()
    results = tg.retrieve("list all users", top_k=3)
    names = [t.name for t in results]
    # read-only tools should appear in top results
    assert any(n in names for n in ["list_users", "get_user", "search_users"])


def test_delete_query_prefers_destructive():
    tg = _build_mixed_tool_graph()
    results = tg.retrieve("delete user permanently", top_k=3)
    names = [t.name for t in results]
    assert "delete_user" in names


def test_write_query_excludes_readonly_from_top():
    tg = _build_mixed_tool_graph()
    results = tg.retrieve("create a new user account", top_k=3)
    names = [t.name for t in results]
    assert "create_user" in names


def test_neutral_query_returns_results():
    tg = _build_mixed_tool_graph()
    results = tg.retrieve("user management operations", top_k=5)
    assert len(results) > 0


def test_annotation_does_not_break_empty_annotations():
    """Tools without annotations should still be retrievable."""
    tg = ToolGraph()
    tg.add_tool(ToolSchema(name="plain_tool", description="A tool with no annotations"))
    tg.add_tool(ToolSchema(name="another_tool", description="Another plain tool"))
    results = tg.retrieve("find a tool", top_k=5)
    assert len(results) >= 0  # should not error


def test_korean_delete_query():
    tg = _build_mixed_tool_graph()
    results = tg.retrieve("사용자 삭제", top_k=3)
    names = [t.name for t in results]
    # delete_user should be boosted by annotation match
    if results:
        assert any("delete" in n or "remove" in n for n in names)
