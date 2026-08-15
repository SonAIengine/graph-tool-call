"""Deterministic goal-state evaluator for multi-tool trajectories."""

from __future__ import annotations

import re
from typing import Any

from .schema import (
    EvaluationCheck,
    GoalEvaluation,
    GoalExecutionRecord,
    MilestoneSpec,
    ObservedToolCall,
    ScenarioSpec,
    StateAssertion,
)

_MISSING = object()
_PATH_TOKEN = re.compile(r"(?:^|\.)([^.\[\]]+)|\[([0-9]+)\]")


def evaluate_goal_execution(
    scenario: ScenarioSpec | dict[str, Any],
    record: GoalExecutionRecord,
) -> GoalEvaluation:
    """Evaluate a trajectory without requiring one brittle exact tool list.

    Required milestones are matched to successful calls, then dependency,
    binding, state, schema, budget, and safety checks are evaluated. The goal
    passes only when every hard check passes and the runner completed.
    """

    spec = scenario if isinstance(scenario, ScenarioSpec) else ScenarioSpec.from_dict(scenario)
    checks: list[EvaluationCheck] = []
    matched = _match_milestones(spec.milestones, record.calls)
    required = [item for item in spec.milestones if item.required]

    for milestone in required:
        sequence = matched.get(milestone.id)
        checks.append(
            EvaluationCheck(
                category="milestone",
                code=("milestone_completed" if sequence is not None else "missing_milestone"),
                passed=sequence is not None,
                subject=milestone.id,
                expected=list(milestone.tools),
                observed=_tool_at_sequence(record.calls, sequence),
            )
        )

    for constraint in spec.dependency_constraints:
        before = matched.get(constraint.before)
        after = matched.get(constraint.after)
        passed = before is not None and after is not None and before < after
        checks.append(
            EvaluationCheck(
                category="dependency",
                code=("dependency_order_valid" if passed else "invalid_dependency_order"),
                passed=passed,
                subject=f"{constraint.before}->{constraint.after}",
                expected="before",
                observed={"before_sequence": before, "after_sequence": after},
            )
        )

    for constraint in spec.binding_constraints:
        source = _call_at_sequence(record.calls, matched.get(constraint.source_milestone))
        target = _call_at_sequence(record.calls, matched.get(constraint.target_milestone))
        source_value = _read_path(source.output, constraint.source_path) if source else _MISSING
        target_value = _read_path(target.args, constraint.target_arg) if target else _MISSING
        passed = source_value is not _MISSING and source_value == target_value
        checks.append(
            EvaluationCheck(
                category="binding",
                code=("binding_valid" if passed else "binding_mismatch"),
                passed=passed,
                subject=(
                    f"{constraint.source_milestone}.{constraint.source_path}"
                    f"->{constraint.target_milestone}.{constraint.target_arg}"
                ),
                expected=source_value if source_value is not _MISSING else "<missing>",
                observed=target_value if target_value is not _MISSING else "<missing>",
            )
        )

    for assertion in spec.final_state_assertions:
        scope = _assertion_scope(assertion, spec=spec, record=record)
        observed = _read_path(scope, assertion.path)
        passed = _evaluate_operator(observed, assertion.operator, assertion.value)
        checks.append(
            EvaluationCheck(
                category="state",
                code=("state_assertion_valid" if passed else "goal_state_mismatch"),
                passed=passed,
                subject=f"{assertion.scope}.{assertion.path}",
                expected={"operator": assertion.operator, "value": assertion.value},
                observed=observed if observed is not _MISSING else "<missing>",
            )
        )

    forbidden = set(spec.forbidden_tools)
    for call in record.calls:
        if call.tool in forbidden:
            checks.append(
                EvaluationCheck(
                    category="policy",
                    code="forbidden_tool_called",
                    passed=False,
                    subject=call.tool,
                    expected="not called",
                    observed=call.sequence,
                )
            )

    if spec.max_calls is not None:
        checks.append(
            EvaluationCheck(
                category="budget",
                code=(
                    "call_budget_valid"
                    if len(record.calls) <= spec.max_calls
                    else "max_calls_exceeded"
                ),
                passed=len(record.calls) <= spec.max_calls,
                subject="max_calls",
                expected=spec.max_calls,
                observed=len(record.calls),
            )
        )
    if spec.max_replans is not None:
        checks.append(
            EvaluationCheck(
                category="budget",
                code=(
                    "replan_budget_valid"
                    if record.replans <= spec.max_replans
                    else "max_replans_exceeded"
                ),
                passed=record.replans <= spec.max_replans,
                subject="max_replans",
                expected=spec.max_replans,
                observed=record.replans,
            )
        )
    if spec.timeout_sec is not None:
        timeout_ms = int(spec.timeout_sec * 1000)
        checks.append(
            EvaluationCheck(
                category="budget",
                code=(
                    "latency_budget_valid"
                    if record.latency_ms <= timeout_ms
                    else "timeout_exceeded"
                ),
                passed=record.latency_ms <= timeout_ms,
                subject="timeout_sec",
                expected=spec.timeout_sec,
                observed=record.latency_ms / 1000,
            )
        )

    schema_values = [call.schema_valid for call in record.calls if call.schema_valid is not None]
    if schema_values:
        schema_passed = all(schema_values)
        checks.append(
            EvaluationCheck(
                category="schema",
                code=("schema_valid" if schema_passed else "schema_invalid"),
                passed=schema_passed,
                subject="tool_calls",
                expected=len(schema_values),
                observed=sum(bool(value) for value in schema_values),
            )
        )

    if not record.success:
        checks.append(
            EvaluationCheck(
                category="execution",
                code="execution_failed",
                passed=False,
                subject="runner",
                expected="completed",
                observed="failed",
            )
        )

    metrics = _metrics(spec, record, matched, checks)
    goal_completed = record.success and all(check.passed for check in checks)
    metrics["goal_completion"] = float(goal_completed)
    failures = tuple(dict.fromkeys(check.code for check in checks if not check.passed))
    return GoalEvaluation(
        scenario_id=spec.id,
        goal_completed=goal_completed,
        metrics=metrics,
        matched_milestones=dict(matched),
        checks=tuple(checks),
        failure_reason_codes=failures,
    )


def _match_milestones(
    milestones: tuple[MilestoneSpec, ...],
    calls: tuple[ObservedToolCall, ...],
) -> dict[str, int]:
    eligible: dict[int, list[int]] = {}
    for milestone_index, milestone in enumerate(milestones):
        eligible[milestone_index] = [
            call.sequence
            for call in sorted(calls, key=lambda item: item.sequence)
            if call.success
            and call.tool in milestone.tools
            and _args_match(call.args, milestone.match_args)
        ]

    owner_by_sequence: dict[int, int] = {}

    def assign(milestone_index: int, visited: set[int]) -> bool:
        for sequence in eligible[milestone_index]:
            if sequence in visited:
                continue
            visited.add(sequence)
            owner = owner_by_sequence.get(sequence)
            if owner is not None and not assign(owner, visited):
                continue
            owner_by_sequence[sequence] = milestone_index
            return True
        return False

    order = sorted(
        range(len(milestones)),
        key=lambda index: (
            not milestones[index].required,
            -len(milestones[index].match_args),
            len(milestones[index].tools),
            index,
        ),
    )
    for milestone_index in order:
        assign(milestone_index, set())
    return {
        milestones[milestone_index].id: sequence
        for sequence, milestone_index in owner_by_sequence.items()
    }


def _args_match(args: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(_read_path(args, path) == value for path, value in expected.items())


def _metrics(
    spec: ScenarioSpec,
    record: GoalExecutionRecord,
    matched: dict[str, int],
    checks: list[EvaluationCheck],
) -> dict[str, float | int | None]:
    required = [item for item in spec.milestones if item.required]
    required_ids = {item.id for item in required}
    completed = len(required_ids & set(matched))
    matched_sequences = set(matched.values())
    extraneous = sum(1 for call in record.calls if call.sequence not in matched_sequences)
    dependency = [item for item in checks if item.category == "dependency"]
    binding = [item for item in checks if item.category == "binding"]
    state = [item for item in checks if item.category == "state"]
    schema_values = [call.schema_valid for call in record.calls if call.schema_valid is not None]
    failed_calls = [call for call in record.calls if not call.success]
    return {
        "candidate_required_tool_recall": _tool_set_recall(required, record.candidate_tools),
        "plan_required_tool_recall": _tool_set_recall(required, record.planned_tools),
        "execution_required_tool_recall": _ratio(completed, len(required)),
        "required_tool_recall": _ratio(completed, len(required)),
        "milestone_completion": _ratio(completed, len(required)),
        "dependency_order_accuracy": _check_ratio(dependency),
        "binding_accuracy": _check_ratio(binding),
        "final_state_accuracy": _check_ratio(state),
        "schema_valid_call_rate": (
            _ratio(sum(bool(value) for value in schema_values), len(schema_values))
            if schema_values
            else None
        ),
        "extraneous_call_rate": _ratio(extraneous, len(record.calls)),
        "policy_violation_count": sum(
            1 for item in checks if item.category == "policy" and not item.passed
        ),
        "call_count": len(record.calls),
        "replan_count": record.replans,
        "latency_ms": record.latency_ms,
        "recovery_attempted": int(bool(failed_calls or record.replans)),
        "recovery_success": (int(record.success) if failed_calls or record.replans else None),
        "goal_completion": 0.0,
    }


def _tool_set_recall(
    milestones: list[MilestoneSpec],
    observed_tools: tuple[str, ...],
) -> float | None:
    if not observed_tools:
        return None
    observed = set(observed_tools)
    hits = sum(1 for item in milestones if observed.intersection(item.tools))
    return _ratio(hits, len(milestones))


def _check_ratio(checks: list[EvaluationCheck]) -> float:
    return _ratio(sum(item.passed for item in checks), len(checks)) if checks else 1.0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _assertion_scope(
    assertion: StateAssertion,
    *,
    spec: ScenarioSpec,
    record: GoalExecutionRecord,
) -> Any:
    if assertion.scope == "final_state":
        return record.final_state
    if assertion.scope == "initial_state":
        return spec.initial_state
    if assertion.scope == "output":
        return record.output
    raise ValueError(f"unsupported assertion scope: {assertion.scope!r}")


def _evaluate_operator(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return observed is not _MISSING
    if operator == "not_exists":
        return observed is _MISSING
    if observed is _MISSING:
        return False
    if operator == "eq":
        return observed == expected
    if operator == "ne":
        return observed != expected
    if operator == "contains":
        try:
            return expected in observed
        except TypeError:
            return False
    if operator == "in":
        try:
            return observed in expected
        except TypeError:
            return False
    try:
        if operator == "gt":
            return bool(observed > expected)
        if operator == "gte":
            return bool(observed >= expected)
        if operator == "lt":
            return bool(observed < expected)
        if operator == "lte":
            return bool(observed <= expected)
    except TypeError:
        return False
    raise ValueError(f"unsupported assertion operator: {operator!r}")


def _read_path(value: Any, path: str) -> Any:
    current = value
    normalized = str(path or "").strip()
    if normalized in ("", "$"):
        return current
    if normalized.startswith("$"):
        normalized = normalized[1:]
        if normalized.startswith("."):
            normalized = normalized[1:]
    position = 0
    for match in _PATH_TOKEN.finditer(normalized):
        if match.start() != position:
            return _MISSING
        key, index = match.groups()
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                return _MISSING
            current = current[key]
        else:
            idx = int(index)
            if not isinstance(current, (list, tuple)) or idx >= len(current):
                return _MISSING
            current = current[idx]
        position = match.end()
    return current if position == len(normalized) else _MISSING


def _call_at_sequence(
    calls: tuple[ObservedToolCall, ...], sequence: int | None
) -> ObservedToolCall | None:
    if sequence is None:
        return None
    return next((call for call in calls if call.sequence == sequence), None)


def _tool_at_sequence(calls: tuple[ObservedToolCall, ...], sequence: int | None) -> str:
    call = _call_at_sequence(calls, sequence)
    return call.tool if call else ""
