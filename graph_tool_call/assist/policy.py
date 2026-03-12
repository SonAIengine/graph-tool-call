"""Execution policy layer for tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from graph_tool_call.assist.validator import ValidationResult, validate_tool_call
from graph_tool_call.core.tool import ToolSchema


class ToolCallDecision(str, Enum):
    """Policy decision for a tool call."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class ToolCallPolicy:
    """Policy settings for deciding whether a tool call may execute."""

    confirm_on_corrections: bool = True
    confirm_on_non_idempotent_write: bool = True
    confirm_on_open_world: bool = True
    confirm_on_destructive: bool = True
    deny_on_errors: bool = True
    deny_destructive_with_corrections: bool = True


@dataclass
class ToolCallAssessment:
    """Final execution assessment for a tool call."""

    decision: ToolCallDecision
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation: ValidationResult | None = None


def assess_tool_call(
    call: dict[str, Any],
    tools: dict[str, ToolSchema],
    *,
    policy: ToolCallPolicy | None = None,
    fuzzy_threshold: float = 0.7,
) -> ToolCallAssessment:
    """Assess whether a tool call should be allowed, confirmed, or denied."""
    active_policy = policy or ToolCallPolicy()
    validation = validate_tool_call(call, tools, fuzzy_threshold=fuzzy_threshold)

    decision = ToolCallDecision.ALLOW
    reasons: list[str] = []

    if validation.errors and active_policy.deny_on_errors:
        decision = ToolCallDecision.DENY
        reasons.extend(validation.errors)
        return ToolCallAssessment(
            decision=decision,
            tool_name=validation.tool_name,
            arguments=validation.arguments,
            reasons=reasons,
            warnings=list(validation.warnings),
            validation=validation,
        )

    tool = tools.get(validation.tool_name)
    has_corrections = bool(validation.corrections)
    if has_corrections and active_policy.confirm_on_corrections:
        decision = ToolCallDecision.CONFIRM
        reasons.append("tool call was auto-corrected before execution")

    if tool is not None and tool.annotations is not None:
        annotations = tool.annotations

        if annotations.destructive_hint:
            if has_corrections and active_policy.deny_destructive_with_corrections:
                decision = ToolCallDecision.DENY
                reasons.append("destructive tool call was auto-corrected")
            elif active_policy.confirm_on_destructive and decision != ToolCallDecision.DENY:
                decision = ToolCallDecision.CONFIRM
                reasons.append("destructive tool requires confirmation")

        if (
            annotations.read_only_hint is False
            and annotations.idempotent_hint is False
            and active_policy.confirm_on_non_idempotent_write
            and decision != ToolCallDecision.DENY
        ):
            decision = ToolCallDecision.CONFIRM
            reasons.append("non-idempotent write requires confirmation")

        if (
            annotations.open_world_hint
            and active_policy.confirm_on_open_world
            and decision != ToolCallDecision.DENY
        ):
            decision = ToolCallDecision.CONFIRM
            reasons.append("open-world tool requires confirmation")

    return ToolCallAssessment(
        decision=decision,
        tool_name=validation.tool_name,
        arguments=validation.arguments,
        reasons=reasons,
        warnings=list(validation.warnings),
        validation=validation,
    )
