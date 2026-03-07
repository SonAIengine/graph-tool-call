"""Tests for conflict detection module."""

from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.analyze.conflict import detect_conflicts
from graph_tool_call.core.tool import MCPAnnotations, ToolSchema


def _api_tool(name: str, method: str, path: str, **kwargs) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=f"{method.upper()} {path}",
        parameters=[],
        metadata={"method": method, "path": path},
        **kwargs,
    )


class TestWriteConflicts:
    def test_put_vs_delete(self):
        tools = [
            _api_tool("updateUser", "put", "/users/{id}"),
            _api_tool("deleteUser", "delete", "/users/{id}"),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) == 1
        names = {conflicts[0].source, conflicts[0].target}
        assert names == {"updateUser", "deleteUser"}

    def test_patch_vs_delete(self):
        tools = [
            _api_tool("patchUser", "patch", "/users/{id}"),
            _api_tool("deleteUser", "delete", "/users/{id}"),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) == 1

    def test_no_conflict_different_resources(self):
        tools = [
            _api_tool("updateUser", "put", "/users/{id}"),
            _api_tool("deleteOrder", "delete", "/orders/{id}"),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) == 0

    def test_multiple_posts_same_resource(self):
        tools = [
            _api_tool("createUser", "post", "/users"),
            _api_tool("importUsers", "post", "/users"),
        ]
        conflicts = detect_conflicts(tools, min_confidence=0.5)
        assert len(conflicts) == 1

    def test_get_no_conflict(self):
        tools = [
            _api_tool("getUser", "get", "/users/{id}"),
            _api_tool("listUsers", "get", "/users"),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) == 0


class TestAnnotationConflicts:
    def test_destructive_vs_writer(self):
        tools = [
            _api_tool(
                "deleteUser",
                "delete",
                "/users/{id}",
                annotations=MCPAnnotations(destructive_hint=True),
            ),
            _api_tool(
                "updateUser",
                "put",
                "/users/{id}",
                annotations=MCPAnnotations(destructive_hint=False),
            ),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) >= 1

    def test_no_conflict_read_only(self):
        tools = [
            _api_tool(
                "getUser",
                "get",
                "/users/{id}",
                annotations=MCPAnnotations(read_only_hint=True),
            ),
            _api_tool(
                "listUsers",
                "get",
                "/users",
                annotations=MCPAnnotations(read_only_hint=True),
            ),
        ]
        conflicts = detect_conflicts(tools)
        assert len(conflicts) == 0


class TestApplyConflicts:
    def test_apply_to_graph(self):
        tg = ToolGraph()
        tg.add_tool(_api_tool("updateUser", "put", "/users/{id}"))
        tg.add_tool(_api_tool("deleteUser", "delete", "/users/{id}"))
        added = tg.apply_conflicts()
        assert added >= 1
        assert tg.graph.has_edge("updateUser", "deleteUser") or tg.graph.has_edge(
            "deleteUser", "updateUser"
        )

    def test_no_duplicate_edges(self):
        tg = ToolGraph()
        tg.add_tool(_api_tool("updateUser", "put", "/users/{id}"))
        tg.add_tool(_api_tool("deleteUser", "delete", "/users/{id}"))
        added1 = tg.apply_conflicts()
        added2 = tg.apply_conflicts()
        assert added1 >= 1
        assert added2 == 0
