"""Plan and ExecutionTrace dataclasses.

``Plan`` is the artifact produced by Stage 2 (Path Synthesizer) of the
Plan-and-Execute architecture. It's consumed by ``PlanRunner`` (Stage 3).
Both are intentionally plain dataclasses — serializable, introspectable,
easy to hand-craft for testing.

The schema explicitly does NOT include fan-out / conditional branching in
v1 (per design doc §16 decision 6). Future versions can add optional
fields (``foreach``, ``condition``) on ``PlanStep``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    """A single step in a Plan.

    ``args`` may contain binding placeholders of the form
    ``${step_id.json.path}`` or ``${input.keyword}``. These are resolved
    at runtime by ``resolve_bindings`` using the accumulated step context.
    """

    id: str                                    # "s1", "s2", ...
    tool: str                                  # function_name (graph node name)
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""                        # why this step exists (for audit)
    timeout_ms: int | None = None
    retryable: bool = False                    # reserved for v1.1 retry policy
    # Top-level keys the synthesizer expects in this tool's response,
    # derived from ``produces[].json_path``. Used by PlanRunner to detect
    # envelope wrappers (e.g. ``{code, message, payload: {...}}``) when the
    # ingest captured the wrapped fields without the wrapper itself. Empty
    # list means "no hint" — the runner then leaves the response untouched.
    response_root_keys: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """Executable plan — ordered steps with binding references.

    v1 scope: **linear execution only**. Steps run in listed order. No
    fan-out, no conditional branching, no parallelism. Each step may
    reference earlier step outputs via ``${sN.path}`` bindings.

    ``output_binding`` designates which step's (or sub-path's) result is
    the final answer. If unset, runner returns the last step's result.
    """

    id: str                                    # uuid
    goal: str                                  # user requirement summary
    steps: list[PlanStep] = field(default_factory=list)
    output_binding: str | None = None          # e.g. "${s2.body}"
    created_at: str = ""                       # ISO8601
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepTrace:
    """Record of a single step execution."""

    id: str
    tool: str
    args_resolved: dict[str, Any] = field(default_factory=dict)
    output: Any = None                         # set on success
    error: dict[str, Any] | None = None        # set on failure
    duration_ms: int = 0
    retries: int = 0


@dataclass
class ExecutionTrace:
    """Result of a full Plan execution."""

    plan_id: str
    success: bool
    steps: list[StepTrace] = field(default_factory=list)
    output: Any = None                         # plan.output_binding resolved
    failed_step: str | None = None
    total_duration_ms: int = 0
    started_at: str = ""
    ended_at: str = ""
