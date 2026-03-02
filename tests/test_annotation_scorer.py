"""Test annotation scorer: alignment between intent and annotations."""

from graph_tool_call.core.tool import MCPAnnotations, ToolSchema
from graph_tool_call.retrieval.annotation_scorer import (
    compute_annotation_scores,
    score_annotation_match,
)
from graph_tool_call.retrieval.intent import QueryIntent


def test_perfect_read_match():
    intent = QueryIntent(read_intent=1.0)
    ann = MCPAnnotations(read_only_hint=True)
    score = score_annotation_match(intent, ann)
    assert score == 1.0


def test_write_vs_readonly_mismatch():
    intent = QueryIntent(write_intent=1.0)
    ann = MCPAnnotations(read_only_hint=True)
    score = score_annotation_match(intent, ann)
    assert score == 0.0


def test_delete_vs_destructive_match():
    intent = QueryIntent(delete_intent=1.0)
    ann = MCPAnnotations(destructive_hint=True, read_only_hint=False)
    score = score_annotation_match(intent, ann)
    assert score > 0.7


def test_delete_vs_readonly_mismatch():
    intent = QueryIntent(delete_intent=1.0)
    ann = MCPAnnotations(read_only_hint=True)
    score = score_annotation_match(intent, ann)
    assert score < 0.2


def test_neutral_intent_returns_neutral():
    intent = QueryIntent()
    ann = MCPAnnotations(read_only_hint=True)
    score = score_annotation_match(intent, ann)
    assert score == 0.5


def test_no_annotations_returns_neutral():
    intent = QueryIntent(read_intent=1.0)
    score = score_annotation_match(intent, None)
    assert score == 0.5


def test_compute_scores_neutral_intent_empty():
    intent = QueryIntent()
    tools = {
        "tool_a": ToolSchema(
            name="tool_a",
            annotations=MCPAnnotations(read_only_hint=True),
        ),
    }
    scores = compute_annotation_scores(intent, tools)
    assert scores == {}


def test_compute_scores_read_intent():
    intent = QueryIntent(read_intent=1.0)
    tools = {
        "read_tool": ToolSchema(
            name="read_tool",
            annotations=MCPAnnotations(read_only_hint=True),
        ),
        "write_tool": ToolSchema(
            name="write_tool",
            annotations=MCPAnnotations(read_only_hint=False),
        ),
        "no_ann": ToolSchema(name="no_ann"),
    }
    scores = compute_annotation_scores(intent, tools)
    assert scores.get("read_tool", 0) > scores.get("write_tool", 0)
    assert "no_ann" not in scores  # neutral, not included


def test_compute_scores_delete_intent():
    intent = QueryIntent(delete_intent=1.0)
    tools = {
        "delete_tool": ToolSchema(
            name="delete_tool",
            annotations=MCPAnnotations(destructive_hint=True, read_only_hint=False),
        ),
        "read_tool": ToolSchema(
            name="read_tool",
            annotations=MCPAnnotations(read_only_hint=True, destructive_hint=False),
        ),
    }
    scores = compute_annotation_scores(intent, tools)
    assert scores["delete_tool"] > scores["read_tool"]
