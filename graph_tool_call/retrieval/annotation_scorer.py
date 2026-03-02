"""Annotation-aware scoring: align query intent with MCP tool annotations."""

from __future__ import annotations

from graph_tool_call.core.tool import MCPAnnotations, ToolSchema
from graph_tool_call.retrieval.intent import QueryIntent

_NEUTRAL = 0.5


def score_annotation_match(intent: QueryIntent, annotations: MCPAnnotations | None) -> float:
    """Score alignment between query intent and tool annotations.

    Returns a float in [0.0, 1.0]:
    - 1.0 = perfect match (e.g., read intent + readOnly tool)
    - 0.5 = neutral (no signal from intent or annotation)
    - 0.0 = hard mismatch (e.g., write intent + readOnly tool)
    """
    if annotations is None or intent.is_neutral:
        return _NEUTRAL

    scores: list[float] = []
    weights: list[float] = []

    # read_intent vs readOnlyHint
    if intent.read_intent > 0 and annotations.read_only_hint is not None:
        if annotations.read_only_hint:
            scores.append(1.0)
        else:
            scores.append(0.3)  # not readOnly but not a mismatch
        weights.append(intent.read_intent)

    # write_intent vs readOnlyHint (inverse)
    if intent.write_intent > 0 and annotations.read_only_hint is not None:
        if annotations.read_only_hint:
            scores.append(0.0)  # hard mismatch: write intent + readOnly tool
        else:
            scores.append(1.0)
        weights.append(intent.write_intent)

    # delete_intent vs destructiveHint
    if intent.delete_intent > 0 and annotations.destructive_hint is not None:
        if annotations.destructive_hint:
            scores.append(1.0)  # match: delete intent + destructive tool
        else:
            scores.append(0.1)
        weights.append(intent.delete_intent)

    # delete_intent vs readOnlyHint (mismatch check)
    if intent.delete_intent > 0 and annotations.read_only_hint is not None:
        if annotations.read_only_hint:
            scores.append(0.0)  # hard mismatch: delete intent + readOnly tool
        else:
            scores.append(0.7)
        weights.append(intent.delete_intent * 0.5)

    if not scores:
        return _NEUTRAL

    total_weight = sum(weights)
    if total_weight == 0:
        return _NEUTRAL

    return sum(s * w for s, w in zip(scores, weights)) / total_weight


def compute_annotation_scores(
    intent: QueryIntent,
    tools: dict[str, ToolSchema],
) -> dict[str, float]:
    """Compute annotation alignment scores for all tools.

    Returns an empty dict if intent is neutral (no noise injection).
    """
    if intent.is_neutral:
        return {}

    scores: dict[str, float] = {}
    for name, tool in tools.items():
        score = score_annotation_match(intent, tool.annotations)
        if score != _NEUTRAL:
            scores[name] = score

    return scores
