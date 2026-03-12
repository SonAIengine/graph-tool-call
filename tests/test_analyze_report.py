"""Tests for operational analysis reporting."""

from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import MCPAnnotations, ToolSchema


def test_analyze_report_counts_duplicates_conflicts_and_orphans():
    tg = ToolGraph()
    tg.add_tool(
        ToolSchema(
            name="create_user",
            description="Create user",
            metadata={"method": "POST", "path": "/users"},
        )
    )
    tg.add_tool(
        ToolSchema(
            name="createUser",
            description="Create user account",
            metadata={"method": "POST", "path": "/users"},
        )
    )
    tg.add_tool(
        ToolSchema(
            name="delete_user",
            description="Delete user",
            metadata={"method": "DELETE", "path": "/users/{id}"},
            annotations=MCPAnnotations(destructive_hint=True),
        )
    )
    tg.add_tool(ToolSchema(name="lonely_tool", description="Standalone"))
    tg.add_category("user_ops")
    tg.assign_category("create_user", "user_ops")
    tg.assign_category("createUser", "user_ops")
    tg.assign_category("delete_user", "user_ops")

    report = tg.analyze(duplicate_threshold=0.7, conflict_min_confidence=0.6)
    payload = report.to_dict()

    assert report.tool_count == 4
    assert report.category_count == 1
    assert report.orphan_tool_count >= 1
    assert "lonely_tool" in report.orphan_tools
    assert report.conflict_count >= 1
    assert report.duplicate_count >= 1
    assert payload["categories"][0]["name"] == "user_ops"
    assert "belongs_to" in report.relation_counts
