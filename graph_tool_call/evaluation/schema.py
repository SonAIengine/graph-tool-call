"""Stable contracts for end-to-end tool-use goal evaluation.

The evaluator deliberately describes outcomes instead of one exact plan. A
scenario can allow alternative tools while still requiring milestones,
dependency order, value bindings, safety constraints, and final state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MilestoneSpec:
    """One required or optional semantic step in a tool-use trajectory."""

    id: str
    tools: tuple[str, ...]
    required: bool = True
    target: bool = False
    match_args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MilestoneSpec:
        return cls(
            id=str(value.get("id") or ""),
            tools=tuple(str(item) for item in (value.get("tools") or []) if item),
            required=bool(value.get("required", True)),
            target=bool(value.get("target", False)),
            match_args=dict(value.get("match_args") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tools": list(self.tools),
            "required": self.required,
            "target": self.target,
            "match_args": dict(self.match_args),
        }


@dataclass(frozen=True)
class DependencyConstraint:
    """Require one milestone to execute before another milestone."""

    before: str
    after: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DependencyConstraint:
        return cls(before=str(value.get("before") or ""), after=str(value.get("after") or ""))

    def to_dict(self) -> dict[str, str]:
        return {"before": self.before, "after": self.after}


@dataclass(frozen=True)
class BindingConstraint:
    """Require a source output value to be passed into a later tool argument."""

    source_milestone: str
    source_path: str
    target_milestone: str
    target_arg: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BindingConstraint:
        return cls(
            source_milestone=str(value.get("source_milestone") or ""),
            source_path=str(value.get("source_path") or ""),
            target_milestone=str(value.get("target_milestone") or ""),
            target_arg=str(value.get("target_arg") or ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_milestone": self.source_milestone,
            "source_path": self.source_path,
            "target_milestone": self.target_milestone,
            "target_arg": self.target_arg,
        }


@dataclass(frozen=True)
class StateAssertion:
    """A deterministic assertion against initial state, final state, or output."""

    path: str
    operator: str = "eq"
    value: Any = None
    scope: str = "final_state"

    def __post_init__(self) -> None:
        if self.scope not in {"initial_state", "final_state", "output"}:
            raise ValueError(f"unsupported assertion scope: {self.scope!r}")
        if self.operator not in {
            "eq",
            "ne",
            "exists",
            "not_exists",
            "contains",
            "in",
            "gt",
            "gte",
            "lt",
            "lte",
        }:
            raise ValueError(f"unsupported assertion operator: {self.operator!r}")
        if not self.path.strip() and self.path != "$":
            raise ValueError("state assertion path must be non-empty")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StateAssertion:
        return cls(
            path=str(value.get("path") or ""),
            operator=str(value.get("operator") or "eq"),
            value=value.get("value"),
            scope=str(value.get("scope") or "final_state"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "path": self.path,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass(frozen=True)
class ScenarioSpec:
    """Versioned goal contract used by deterministic and live benchmarks."""

    id: str
    query: str
    milestones: tuple[MilestoneSpec, ...]
    dependency_constraints: tuple[DependencyConstraint, ...] = ()
    binding_constraints: tuple[BindingConstraint, ...] = ()
    final_state_assertions: tuple[StateAssertion, ...] = ()
    initial_state: dict[str, Any] = field(default_factory=dict)
    user_context: dict[str, Any] = field(default_factory=dict)
    forbidden_tools: tuple[str, ...] = ()
    max_calls: int | None = None
    max_replans: int | None = None
    timeout_sec: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("scenario id must be non-empty")
        if not self.query.strip():
            raise ValueError("scenario query must be non-empty")
        if not self.milestones:
            raise ValueError("scenario must define at least one milestone")
        milestone_ids = [item.id for item in self.milestones]
        if any(not item.id.strip() or not item.tools for item in self.milestones):
            raise ValueError("every milestone requires a non-empty id and at least one tool")
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ValueError("milestone ids must be unique")
        known = set(milestone_ids)
        for item in self.dependency_constraints:
            if item.before not in known or item.after not in known:
                raise ValueError("dependency constraints must reference known milestones")
            if item.before == item.after:
                raise ValueError("dependency constraints cannot reference the same milestone")
        for item in self.binding_constraints:
            if item.source_milestone not in known or item.target_milestone not in known:
                raise ValueError("binding constraints must reference known milestones")
            if not item.source_path or not item.target_arg:
                raise ValueError("binding constraints require source_path and target_arg")
        if self.max_calls is not None and self.max_calls < 1:
            raise ValueError("max_calls must be positive")
        if self.max_replans is not None and self.max_replans < 0:
            raise ValueError("max_replans cannot be negative")
        if self.timeout_sec is not None and self.timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ScenarioSpec:
        assertions = value.get("final_state_assertions")
        if assertions is None:
            assertions = value.get("assertions") or []
        return cls(
            id=str(value.get("id") or ""),
            query=str(value.get("query") or ""),
            milestones=tuple(
                MilestoneSpec.from_dict(item)
                for item in (value.get("milestones") or [])
                if isinstance(item, dict)
            ),
            dependency_constraints=tuple(
                DependencyConstraint.from_dict(item)
                for item in (value.get("dependency_constraints") or [])
                if isinstance(item, dict)
            ),
            binding_constraints=tuple(
                BindingConstraint.from_dict(item)
                for item in (value.get("binding_constraints") or [])
                if isinstance(item, dict)
            ),
            final_state_assertions=tuple(
                StateAssertion.from_dict(item) for item in assertions if isinstance(item, dict)
            ),
            initial_state=dict(value.get("initial_state") or {}),
            user_context=dict(value.get("user_context") or {}),
            forbidden_tools=tuple(
                str(item) for item in (value.get("forbidden_tools") or []) if item
            ),
            max_calls=(int(value["max_calls"]) if value.get("max_calls") is not None else None),
            max_replans=(
                int(value["max_replans"]) if value.get("max_replans") is not None else None
            ),
            timeout_sec=(
                float(value["timeout_sec"]) if value.get("timeout_sec") is not None else None
            ),
            metadata=dict(value.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "milestones": [item.to_dict() for item in self.milestones],
            "dependency_constraints": [item.to_dict() for item in self.dependency_constraints],
            "binding_constraints": [item.to_dict() for item in self.binding_constraints],
            "final_state_assertions": [item.to_dict() for item in self.final_state_assertions],
            "initial_state": dict(self.initial_state),
            "user_context": dict(self.user_context),
            "forbidden_tools": list(self.forbidden_tools),
            "max_calls": self.max_calls,
            "max_replans": self.max_replans,
            "timeout_sec": self.timeout_sec,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ObservedToolCall:
    """Compact, transport-neutral record of one resolved tool invocation."""

    sequence: int
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    success: bool = True
    schema_valid: bool | None = None
    duration_ms: int = 0
    error_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        from graph_tool_call.learning import scrub_trace_payload

        return {
            "sequence": self.sequence,
            "tool": self.tool,
            "args": scrub_trace_payload(dict(self.args)),
            "output": scrub_trace_payload(self.output),
            "success": self.success,
            "schema_valid": self.schema_valid,
            "duration_ms": self.duration_ms,
            "error_kind": self.error_kind,
        }


@dataclass(frozen=True)
class GoalExecutionRecord:
    """Everything the evaluator needs; raw API payload persistence is optional."""

    calls: tuple[ObservedToolCall, ...]
    success: bool
    retrieved_tools: tuple[str, ...] = ()
    candidate_tools: tuple[str, ...] = ()
    planned_tools: tuple[str, ...] = ()
    final_state: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    latency_ms: int = 0
    replans: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_execution_trace(
        cls,
        trace: Any,
        *,
        plan: Any | None = None,
        retrieved_tools: list[str] | tuple[str, ...] = (),
        candidate_tools: list[str] | tuple[str, ...] = (),
        final_state: dict[str, Any] | None = None,
        replans: int = 0,
        schema_valid: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GoalExecutionRecord:
        calls = []
        for sequence, step in enumerate(getattr(trace, "steps", ()) or (), start=1):
            error = getattr(step, "error", None)
            error_kind = str((error or {}).get("kind") or "")
            calls.append(
                ObservedToolCall(
                    sequence=sequence,
                    tool=str(getattr(step, "tool", "")),
                    args=dict(getattr(step, "args_resolved", {}) or {}),
                    output=getattr(step, "output", None),
                    success=error is None,
                    schema_valid=(
                        False
                        if error_kind in {"schema", "validation"}
                        else schema_valid
                        if error is None
                        else None
                    ),
                    duration_ms=int(getattr(step, "duration_ms", 0) or 0),
                    error_kind=error_kind,
                )
            )
        planned_tools = tuple(
            str(getattr(step, "tool", "")) for step in (getattr(plan, "steps", ()) or ())
        )
        return cls(
            calls=tuple(calls),
            success=bool(getattr(trace, "success", False)),
            retrieved_tools=tuple(str(item) for item in retrieved_tools),
            candidate_tools=tuple(str(item) for item in candidate_tools),
            planned_tools=planned_tools,
            final_state=dict(final_state or {}),
            output=getattr(trace, "output", None),
            latency_ms=int(getattr(trace, "total_duration_ms", 0) or 0),
            replans=int(replans),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True)
class EvaluationCheck:
    """One explainable pass/fail item in a goal evaluation."""

    category: str
    code: str
    passed: bool
    subject: str
    expected: Any = None
    observed: Any = None

    def to_dict(self) -> dict[str, Any]:
        from graph_tool_call.learning import scrub_trace_payload

        return {
            "category": self.category,
            "code": self.code,
            "passed": self.passed,
            "subject": self.subject,
            "expected": scrub_trace_payload(self.expected),
            "observed": scrub_trace_payload(self.observed),
        }


@dataclass(frozen=True)
class GoalEvaluation:
    """Deterministic outcome and stage metrics for one scenario execution."""

    scenario_id: str
    goal_completed: bool
    metrics: dict[str, float | int | None]
    matched_milestones: dict[str, int]
    checks: tuple[EvaluationCheck, ...]
    failure_reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "goal_completed": self.goal_completed,
            "metrics": dict(self.metrics),
            "matched_milestones": dict(self.matched_milestones),
            "checks": [item.to_dict() for item in self.checks],
            "failure_reason_codes": list(self.failure_reason_codes),
        }
