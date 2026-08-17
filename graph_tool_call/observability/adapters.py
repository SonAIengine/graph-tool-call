"""Adapters from existing engine result contracts into trace decisions."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from graph_tool_call.learning import scrub_trace_payload

from .recorder import TraceSpanRecorder

_RETRIEVAL_REASON_CODES = {
    "seed": "retrieval.seed_match",
    "graph": "retrieval.graph_score",
    "learning": "retrieval.promoted_learning",
    "action_match": "retrieval.action_match",
    "resource_match": "retrieval.resource_match",
    "module_match": "retrieval.module_match",
    "shape_match": "retrieval.shape_match",
    "contract_match": "retrieval.contract_match",
    "graph_expansion": "retrieval.graph_expansion",
}


def record_retrieval_result(span: TraceSpanRecorder, result: dict[str, Any]) -> None:
    """Record ranked retrieval rows and their score channels."""

    rows = [row for row in (result.get("results") or []) if isinstance(row, dict)]
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    span.set_attribute("result_count", len(rows))
    span.set_attribute("seeds", stats.get("seeds") or [])
    span.set_attribute("visited_nodes", stats.get("visited_nodes"))
    span.set_attribute("visited_edges", stats.get("visited_edges"))
    span.set_attribute("token_budget_used", stats.get("token_budget_used"))
    for rank, row in enumerate(rows, start=1):
        name = str(row.get("name") or "")
        if not name:
            continue
        breakdown = (
            row.get("score_breakdown") if isinstance(row.get("score_breakdown"), dict) else {}
        )
        reasons = [
            reason
            for key, reason in _RETRIEVAL_REASON_CODES.items()
            if _signal_is_active(breakdown.get(key))
        ]
        if breakdown.get("history_demoted"):
            reasons.append("retrieval.history_demoted")
        if not reasons:
            reasons.append("retrieval.rank_score")
        span.decision(
            name,
            "ranked",
            reasons,
            score=_optional_float(row.get("score")),
            rank_after=rank,
            evidence={
                "score_breakdown": breakdown,
                "semantic_evidence": row.get("semantic_evidence") or {},
                "expanded_from": row.get("expanded_from"),
                "edge_evidence": row.get("edge_evidence") or [],
                "learning_evidence": row.get("learning_evidence") or {},
            },
        )


def record_selector_result(span: TraceSpanRecorder, result: dict[str, Any]) -> None:
    """Record the final target choice and every considered candidate."""

    selected = str(result.get("selected_target") or "")
    global_reasons = [str(item) for item in (result.get("reason_codes") or []) if item]
    rank_signals = [row for row in (result.get("rank_signals") or []) if isinstance(row, dict)]
    span.set_attribute("selected_target", selected)
    span.set_attribute("llm_target", result.get("llm_target"))
    span.set_attribute("overrode_llm", bool(result.get("overrode_llm")))
    span.set_attribute("ambiguous", bool(result.get("ambiguous")))
    span.set_attribute("needs_expansion", bool(result.get("needs_expansion")))
    span.set_attribute("decision", result.get("decision"))
    span.set_attribute("recommended_action", result.get("recommended_action"))
    span.set_attribute("margin", result.get("margin"))
    span.set_attribute("policy", result.get("policy"))
    span.set_attribute("policy_revision", result.get("policy_revision"))
    span.set_attribute("override_assessment", result.get("override_assessment") or {})

    for rank, row in enumerate(rank_signals, start=1):
        name = str(row.get("name") or "")
        if not name:
            continue
        is_selected = name == selected or bool(row.get("selected"))
        reasons = list(global_reasons) if is_selected else ["selector.not_final_target"]
        if row.get("llm_target"):
            reasons.append("selector.llm_target")
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        reasons.extend(_selector_evidence_reasons(evidence))
        if is_selected:
            reasons.append("selector.final_target")
        span.decision(
            name,
            "selected" if is_selected else "not_selected",
            reasons,
            score=_optional_float(row.get("selector_score")),
            rank_before=_optional_int(row.get("original_rank")),
            rank_after=rank,
            evidence=row,
        )

    if selected and not rank_signals:
        span.decision(
            selected,
            "selected",
            global_reasons or ["selector.fallback_target"],
            score=_optional_float(result.get("confidence")),
            evidence={"policy": result.get("policy")},
        )
    if not selected:
        span.event("selector.empty", {"reason_codes": global_reasons or ["no_candidates"]})


def record_target_admission(span: TraceSpanRecorder, result: dict[str, Any]) -> None:
    """Record adaptive target-catalog admission and every dropped reason."""

    signals = [row for row in (result.get("admission_signals") or []) if isinstance(row, dict)]
    span.set_attribute("policy_revision", result.get("policy_revision"))
    span.set_attribute("needs_expansion", bool(result.get("needs_expansion")))
    span.set_attribute("recommended_action", result.get("recommended_action"))
    span.set_attribute("reason_codes", result.get("reason_codes") or [])
    span.set_attribute("raw_candidate_count", result.get("raw_candidate_count"))
    span.set_attribute("admitted_candidate_count", result.get("admitted_candidate_count"))
    span.set_attribute("dropped_candidate_count", result.get("dropped_candidate_count"))
    span.set_attribute("token_budget", result.get("token_budget") or {})
    span.set_attribute("score_cliff", result.get("score_cliff") or {})
    for row in signals:
        name = str(row.get("name") or "")
        if not name:
            continue
        admitted = bool(row.get("admitted"))
        reason = str(row.get("decision_reason") or "unknown")
        span.decision(
            name,
            "admitted" if admitted else "omitted",
            [f"target_admission.{reason}"],
            score=_optional_float(row.get("selector_score")),
            rank_before=_optional_int(row.get("retrieval_rank")),
            rank_after=_optional_int(row.get("rank")),
            evidence=row,
        )


def record_dependency_closure(span: TraceSpanRecorder, value: Any) -> None:
    """Record prerequisite expansion, unresolved fields, cycles, and safety."""

    closure = _as_mapping(value)
    target = str(closure.get("target") or "")
    evidence_rows = [row for row in (closure.get("evidence") or []) if isinstance(row, dict)]
    required = [str(item) for item in (closure.get("required_dependencies") or []) if item]
    optional = [str(item) for item in (closure.get("optional_dependencies") or []) if item]
    span.set_attribute("target", target)
    span.set_attribute("complete", bool(closure.get("complete")))
    span.set_attribute("safety", closure.get("safety") or {})
    span.set_attribute("policy_revision", closure.get("policy_revision"))
    if target:
        span.decision(target, "retained", ["dependency.target_preserved"])
    for name in required:
        rows = [row for row in evidence_rows if str(row.get("producer") or "") == name]
        sources = {str(source) for row in rows for source in (row.get("sources") or []) if source}
        reasons = [f"dependency.evidence.{source}" for source in sorted(sources)]
        span.decision(
            name,
            "expanded",
            reasons or ["dependency.required_producer"],
            evidence={"matches": rows},
        )
    for name in optional:
        span.decision(name, "suggested", ["dependency.optional_alternative"])
    for row in closure.get("unresolved_fields") or []:
        if not isinstance(row, dict):
            continue
        subject = str(
            row.get("field_key")
            or row.get("field_name")
            or row.get("semantic_tag")
            or "unknown_field"
        )
        reason = str(row.get("reason") or "unresolved_field")
        span.decision(subject, "unresolved", [f"dependency.{reason}"], evidence=row)
    for index, cycle in enumerate(closure.get("cycles") or [], start=1):
        span.decision(
            f"cycle:{index}",
            "blocked",
            ["dependency.cycle"],
            evidence={"path": cycle},
        )


def record_tool_bundle(span: TraceSpanRecorder, value: Any) -> None:
    """Record contract-projected schema admission under a token budget."""

    bundle = _as_mapping(value)
    admitted = [str(item) for item in (bundle.get("admitted_tools") or []) if item]
    omitted = [str(item) for item in (bundle.get("omitted_tools") or []) if item]
    required = {
        str(item) for item in [bundle.get("target"), *(bundle.get("required_tools") or [])] if item
    }
    optional = {str(item) for item in (bundle.get("optional_tools") or []) if item}
    budget = bundle.get("token_budget") if isinstance(bundle.get("token_budget"), dict) else {}
    span.set_attribute("token_budget", budget)
    span.set_attribute("closure_status", bundle.get("closure_status"))
    span.set_attribute("policy_revision", bundle.get("policy_revision"))
    for rank, name in enumerate(admitted, start=1):
        if name == str(bundle.get("target") or ""):
            reasons = ["admission.target_first"]
        elif name in required:
            reasons = ["admission.required_dependency"]
        elif name in optional:
            reasons = ["admission.optional_within_budget"]
        else:
            reasons = ["admission.within_budget"]
        span.decision(name, "admitted", reasons, rank_after=rank, evidence={"budget": budget})
    for name in omitted:
        reason = (
            "admission.required_budget_insufficient"
            if name in required
            else "admission.token_budget_exceeded"
        )
        span.decision(name, "omitted", [reason], evidence={"budget": budget})


def record_plan(span: TraceSpanRecorder, value: Any) -> None:
    """Record planned tool order without persisting raw arguments."""

    plan = _as_mapping(value)
    span.set_attribute("plan_id", plan.get("id") or plan.get("plan_id"))
    steps = [row for row in (plan.get("steps") or []) if isinstance(row, dict)]
    for rank, step in enumerate(steps, start=1):
        tool = str(step.get("tool") or step.get("tool_name") or "")
        if not tool:
            continue
        span.decision(
            tool,
            "planned",
            ["plan.step_order"],
            rank_after=rank,
            evidence={
                "step_id": step.get("id") or step.get("step_id"),
                "depends_on": step.get("depends_on") or [],
            },
        )


def record_runner_events(span: TraceSpanRecorder, events: list[Any]) -> None:
    """Attach PlanRunner events after applying the common scrub policy."""

    for value in events:
        row = _as_mapping(value)
        event_name = str(row.get("type") or type(value).__name__ or "runner.event")
        span.event(event_name, row)


def _selector_evidence_reasons(evidence: dict[str, Any]) -> list[str]:
    reasons = []
    for key, value in evidence.items():
        if _signal_is_active(value):
            reasons.append(f"selector.evidence.{key}")
    return reasons


def _signal_is_active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return bool(str(value or "").strip())


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        row = value
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        row = value.to_dict()
    elif is_dataclass(value):
        row = asdict(value)
    else:
        row = {}
    clean = scrub_trace_payload(row)
    return clean if isinstance(clean, dict) else {}
