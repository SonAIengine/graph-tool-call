"""Secret-safe execution-flow contracts for plans and tool graphs.

The helpers in this module intentionally separate three concepts:

* ``planned``: ordered steps emitted by a planner;
* ``observed``: planned steps with runner evidence;
* ``inferred``: predecessor/successor candidates derived from graph edges.

Inferred candidates are never presented as an executed plan. Unknown or
bidirectional relationships stay unordered instead of gaining a fabricated
direction in an adapter or UI.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from graph_tool_call.learning import scrub_trace_payload

EXECUTION_FLOW_SCHEMA_VERSION = "1.0"

FLOW_MODE_PLANNED = "planned"
FLOW_MODE_OBSERVED = "observed"
FLOW_MODE_INFERRED = "inferred"

DIRECTION_SOURCE_TO_TARGET = "source_to_target"
DIRECTION_TARGET_TO_SOURCE = "target_to_source"
DIRECTION_UNDIRECTED = "undirected"
DIRECTION_UNKNOWN = "unknown"

_FORWARD_RELATIONS = frozenset(
    {
        "data_flow",
        "precedes",
        "prerequisite_for",
        "produces_consumes",
        "produces_for",
        "run_observed",
    }
)
_REVERSE_RELATIONS = frozenset({"consumes_from", "depends_on"})
_UNDIRECTED_RELATIONS = frozenset(
    {
        "complementary",
        "pairs_with",
        "pairs_well_with",
        "related",
        "similar",
        "similar_to",
    }
)
_BINDING_RE = re.compile(r"^\$\{([A-Za-z0-9_-]+)\.(.+)\}$")
_SAFE_DATA_FLOW_FIELDS = frozenset(
    {
        "from_field",
        "from_path",
        "input_field",
        "link_name",
        "dependency_kind",
        "observed_count",
        "output_field",
        "source_step_id",
        "source_field",
        "source_field_path",
        "target_field",
        "target_field_path",
        "to_field",
        "target_step_id",
        "value_type",
        "workflow_id",
    }
)


def classify_execution_edge(
    edge: dict[str, Any],
    *,
    selected_tool: str | None = None,
) -> dict[str, Any]:
    """Classify one graph edge without inventing an execution direction.

    Graphify data-flow edges use producer ``source`` -> consumer ``target``.
    Explicit ``execution_direction`` metadata wins when an external adapter
    uses a different relation vocabulary.
    """

    source = str(edge.get("source") or "")
    target = str(edge.get("target") or "")
    relation = str(edge.get("relation") or edge.get("kind") or "").lower()
    evidence_sources = _unique_strings(edge.get("evidence_sources") or [])
    direction = _edge_direction(edge, relation, evidence_sources)
    evidence_type = _evidence_type(evidence_sources)
    confidence = _confidence(edge)

    role = None
    counterpart = None
    if selected_tool and selected_tool in {source, target}:
        counterpart = target if selected_tool == source else source
        if direction == DIRECTION_UNDIRECTED or direction == DIRECTION_UNKNOWN:
            role = "related"
        else:
            predecessor, successor = (
                (source, target) if direction == DIRECTION_SOURCE_TO_TARGET else (target, source)
            )
            role = "predecessor" if counterpart == predecessor else "successor"

    data_flow = _safe_data_flow(edge.get("data_flow"))
    return {
        "source": source,
        "target": target,
        "relation": relation or "related",
        "direction": direction,
        "ordered": direction in {DIRECTION_SOURCE_TO_TARGET, DIRECTION_TARGET_TO_SOURCE},
        "role": role,
        "counterpart": counterpart,
        "confidence": confidence,
        "evidence_type": evidence_type,
        "evidence_sources": evidence_sources,
        "data_flow": data_flow,
        "observed_count": _observed_count(data_flow),
    }


def derive_execution_flow(
    *,
    plan: Any | None = None,
    runner_events: list[Any] | None = None,
    trace_steps: list[Any] | None = None,
    graph_edges: list[dict[str, Any]] | None = None,
    selected_tool: str | None = None,
    max_candidates: int = 6,
) -> dict[str, Any]:
    """Build a deterministic, JSON-safe execution-flow artifact.

    Raw argument values and tool outputs are deliberately omitted. Bindings
    retain only field names, source steps/tools, and response paths.
    """

    plan_dict = _plain_dict(plan)
    plan_steps = [row for row in plan_dict.get("steps") or [] if isinstance(row, dict)]
    events = [_plain_dict(value) for value in (runner_events or [])]
    traces = [_plain_dict(value) for value in (trace_steps or [])]
    has_runner_evidence = bool(events or traces)

    steps = _flow_steps(plan_steps, events, traces)
    transitions = _plan_transitions(plan_steps, steps)
    candidates = _candidate_groups(
        graph_edges or [],
        selected_tool=selected_tool,
        max_candidates=max(0, int(max_candidates)),
    )

    if plan_steps:
        mode = FLOW_MODE_OBSERVED if has_runner_evidence else FLOW_MODE_PLANNED
    else:
        mode = FLOW_MODE_INFERRED

    diagnostics: list[str] = []
    if has_runner_evidence and not plan_steps:
        diagnostics.append("runner_evidence_without_plan")
    if not plan_steps and not any(candidates.values()):
        diagnostics.append("no_flow_evidence")
    if candidates["ambiguous"]:
        diagnostics.append("ambiguous_graph_direction")

    inferred_target = selected_tool
    if not inferred_target and plan_steps:
        inferred_target = str(plan_steps[-1].get("tool") or "") or None

    return {
        "schema_version": EXECUTION_FLOW_SCHEMA_VERSION,
        "mode": mode,
        "status": _flow_status(steps, events, plan_steps),
        "plan_id": str(plan_dict.get("id") or plan_dict.get("plan_id") or "") or None,
        "goal": _clean_text(plan_dict.get("goal")),
        "selected_tool": inferred_target,
        "steps": steps,
        "transitions": transitions,
        "candidates": candidates,
        "diagnostics": diagnostics,
    }


def _edge_direction(
    edge: dict[str, Any],
    relation: str,
    evidence_sources: list[str],
) -> str:
    explicit = str(edge.get("execution_direction") or edge.get("direction") or "").lower()
    aliases = {
        "forward": DIRECTION_SOURCE_TO_TARGET,
        "source_to_target": DIRECTION_SOURCE_TO_TARGET,
        "reverse": DIRECTION_TARGET_TO_SOURCE,
        "target_to_source": DIRECTION_TARGET_TO_SOURCE,
        "bidirectional": DIRECTION_UNDIRECTED,
        "undirected": DIRECTION_UNDIRECTED,
        "unknown": DIRECTION_UNKNOWN,
    }
    if explicit in aliases:
        return aliases[explicit]
    if relation in _UNDIRECTED_RELATIONS:
        return DIRECTION_UNDIRECTED
    if relation == "requires":
        # ``requires`` exists in two historical graph contracts. Contract
        # matching emits producer -> consumer, while structural/manual edges
        # express consumer -> prerequisite. Keep both readable without making
        # adapters rewrite stored graphs.
        if isinstance(edge.get("data_flow"), dict) or {
            "api_contract",
            "openapi_link",
        }.intersection(evidence_sources):
            return DIRECTION_SOURCE_TO_TARGET
        return DIRECTION_TARGET_TO_SOURCE
    if relation in _REVERSE_RELATIONS:
        return DIRECTION_TARGET_TO_SOURCE
    if relation in _FORWARD_RELATIONS:
        return DIRECTION_SOURCE_TO_TARGET
    kind = str(edge.get("kind") or "").lower()
    if kind in {"data", "data_flow"} or {"api_contract", "openapi_link"}.intersection(
        evidence_sources
    ):
        return DIRECTION_SOURCE_TO_TARGET
    return DIRECTION_UNKNOWN


def _evidence_type(sources: list[str]) -> str:
    values = set(sources)
    if values.intersection({"proven", "run", "run_observed"}):
        return "observed"
    if values.intersection({"api_contract", "openapi_link"}):
        return "contract"
    if "arazzo" in values:
        return "workflow"
    if values.intersection({"manual", "llm_curated", "llm_validated"}):
        return "curated"
    return "inferred"


def _confidence(edge: dict[str, Any]) -> float | None:
    raw = edge.get("conf_score")
    if raw is None and isinstance(edge.get("confidence"), (int, float)):
        raw = edge.get("confidence")
    try:
        return round(max(0.0, min(1.0, float(raw))), 6) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _observed_count(data_flow: dict[str, Any] | None) -> int:
    if not data_flow:
        return 0
    try:
        return max(0, int(data_flow.get("observed_count") or 0))
    except (TypeError, ValueError):
        return 0


def _safe_data_flow(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    output: dict[str, Any] = {}
    for key in _SAFE_DATA_FLOW_FIELDS:
        item = value.get(key)
        if item in (None, "", [], {}):
            continue
        if key == "observed_count":
            output[key] = _observed_count({"observed_count": item})
        elif isinstance(item, (str, int, float, bool)):
            output[key] = scrub_trace_payload(item)
    return output or None


def _candidate_groups(
    edges: list[dict[str, Any]],
    *,
    selected_tool: str | None,
    max_candidates: int,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "predecessors": [],
        "successors": [],
        "related": [],
        "ambiguous": [],
    }
    if not selected_tool:
        return groups

    by_role: dict[str, dict[str, dict[str, Any]]] = {
        "predecessor": {},
        "successor": {},
        "related": {},
    }
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        item = classify_execution_edge(edge, selected_tool=selected_tool)
        counterpart = str(item.get("counterpart") or "")
        role = str(item.get("role") or "")
        if not counterpart or role not in by_role:
            continue
        current = by_role[role].get(counterpart)
        if current is None or _candidate_sort_key(item) < _candidate_sort_key(current):
            by_role[role][counterpart] = item

    both = set(by_role["predecessor"]).intersection(by_role["successor"])
    for counterpart in sorted(both):
        left = by_role["predecessor"].pop(counterpart)
        right = by_role["successor"].pop(counterpart)
        groups["ambiguous"].append(
            {
                "tool": counterpart,
                "reason": "conflicting_directions",
                "relations": sorted({left["relation"], right["relation"]}),
                "evidence_sources": _unique_strings(
                    [*left["evidence_sources"], *right["evidence_sources"]]
                ),
            }
        )

    groups["predecessors"] = _candidate_rows(by_role["predecessor"], max_candidates)
    groups["successors"] = _candidate_rows(by_role["successor"], max_candidates)
    groups["related"] = _candidate_rows(by_role["related"], max_candidates)
    groups["ambiguous"] = groups["ambiguous"][:max_candidates]
    return groups


def _candidate_rows(values: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rows = []
    for tool, item in values.items():
        rows.append(
            {
                "tool": tool,
                "relation": item["relation"],
                "confidence": item["confidence"],
                "evidence_type": item["evidence_type"],
                "evidence_sources": item["evidence_sources"],
                "data_flow": item["data_flow"],
                "observed_count": item["observed_count"],
            }
        )
    rows.sort(key=_candidate_sort_key)
    return rows[:limit]


def _candidate_sort_key(value: dict[str, Any]) -> tuple[int, float, int, str]:
    evidence_rank = {"observed": 0, "contract": 1, "curated": 2, "inferred": 3}
    return (
        evidence_rank.get(str(value.get("evidence_type") or "inferred"), 4),
        -float(value.get("confidence") or 0.0),
        -int(value.get("observed_count") or 0),
        str(value.get("tool") or value.get("counterpart") or ""),
    )


def _flow_steps(
    plan_steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
    trace_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    runtime: dict[str, dict[str, Any]] = {}
    for event in events:
        step_id = str(event.get("step_id") or "")
        if not step_id:
            continue
        event_type = str(event.get("type") or "")
        state = runtime.setdefault(step_id, {})
        if event_type == "step.started":
            state["status"] = "running"
        elif event_type == "step.retrying":
            state["status"] = "retrying"
            state["attempt"] = _optional_int(event.get("attempt"))
        elif event_type == "step.completed":
            state["status"] = "completed"
            state["duration_ms"] = _optional_int(event.get("duration_ms"))
        elif event_type == "step.failed":
            state["status"] = "failed"
            state["duration_ms"] = _optional_int(event.get("duration_ms"))

    for trace in trace_steps:
        step_id = str(trace.get("id") or trace.get("step_id") or "")
        if not step_id:
            continue
        state = runtime.setdefault(step_id, {})
        if trace.get("error"):
            state["status"] = "failed"
        elif str(trace.get("status") or "").lower() in {"failed", "error", "aborted"}:
            state["status"] = "failed"
        else:
            state["status"] = "completed"
        duration = _optional_int(trace.get("duration_ms"))
        if duration is not None:
            state["duration_ms"] = duration
        retries = _optional_int(trace.get("retries"))
        if retries:
            state["attempt"] = retries + 1

    output = []
    for index, step in enumerate(plan_steps, start=1):
        step_id = str(step.get("id") or step.get("step_id") or f"step-{index}")
        state = runtime.get(step_id) or {}
        output.append(
            {
                "step_id": step_id,
                "tool": str(step.get("tool") or step.get("tool_name") or ""),
                "index": index,
                "status": str(state.get("status") or "planned"),
                "duration_ms": state.get("duration_ms"),
                "attempt": state.get("attempt"),
                "rationale": _clean_text(step.get("rationale")),
                "depends_on": _unique_strings(step.get("depends_on") or []),
                "bindings": _step_bindings(step),
            }
        )
    return output


def _step_bindings(step: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    arg_sources = step.get("arg_sources")
    if isinstance(arg_sources, dict):
        for field, raw_source in arg_sources.items():
            source = raw_source if isinstance(raw_source, dict) else {}
            kind = str(source.get("kind") or "unknown")
            bindings.append(
                {
                    "field": str(field),
                    "kind": kind,
                    "source_step": str(source.get("from_step") or "") or None,
                    "source_tool": str(source.get("from_tool") or "") or None,
                    "path": _clean_path(source.get("path")),
                }
            )
        return bindings

    args = step.get("args")
    if not isinstance(args, dict):
        return bindings
    for field, value in args.items():
        if not isinstance(value, str):
            continue
        match = _BINDING_RE.match(value.strip())
        if not match:
            continue
        source_step, path = match.groups()
        kind = "user_input" if source_step in {"input", "user_input"} else "binding"
        bindings.append(
            {
                "field": str(field),
                "kind": kind,
                "source_step": source_step if kind == "binding" else None,
                "source_tool": None,
                "path": _clean_path(path),
            }
        )
    return bindings


def _plan_transitions(
    plan_steps: list[dict[str, Any]],
    flow_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(row.get("step_id") or ""): row for row in flow_steps}
    tool_by_step = {
        str(step.get("id") or step.get("step_id") or f"step-{index}"): str(
            step.get("tool") or step.get("tool_name") or ""
        )
        for index, step in enumerate(plan_steps, start=1)
    }
    transitions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()

    for index, step in enumerate(flow_steps):
        target_step = str(step.get("step_id") or "")
        dependencies = list(step.get("depends_on") or [])
        dependencies.extend(
            str(binding.get("source_step") or "")
            for binding in step.get("bindings") or []
            if binding.get("kind") == "binding"
        )
        for source_step in _unique_strings(dependencies):
            binding_rows = [
                row for row in step.get("bindings") or [] if row.get("source_step") == source_step
            ]
            if binding_rows:
                for binding in binding_rows:
                    _append_transition(
                        transitions,
                        seen,
                        source_step=source_step,
                        target_step=target_step,
                        source_tool=tool_by_step.get(source_step),
                        target_tool=step.get("tool"),
                        relation="data_flow",
                        field=binding.get("field"),
                        path=binding.get("path"),
                        observed=_transition_observed(by_id, source_step, target_step),
                    )
            else:
                _append_transition(
                    transitions,
                    seen,
                    source_step=source_step,
                    target_step=target_step,
                    source_tool=tool_by_step.get(source_step),
                    target_tool=step.get("tool"),
                    relation="depends_on",
                    field=None,
                    path=None,
                    observed=_transition_observed(by_id, source_step, target_step),
                )

        if index > 0:
            previous = flow_steps[index - 1]
            previous_id = str(previous.get("step_id") or "")
            if not any(
                row["source_step"] == previous_id and row["target_step"] == target_step
                for row in transitions
            ):
                _append_transition(
                    transitions,
                    seen,
                    source_step=previous_id,
                    target_step=target_step,
                    source_tool=previous.get("tool"),
                    target_tool=step.get("tool"),
                    relation="precedes",
                    field=None,
                    path=None,
                    observed=_transition_observed(by_id, previous_id, target_step),
                )
    return transitions


def _append_transition(
    transitions: list[dict[str, Any]],
    seen: set[tuple[str, str, str | None]],
    *,
    source_step: str,
    target_step: str,
    source_tool: Any,
    target_tool: Any,
    relation: str,
    field: Any,
    path: Any,
    observed: bool,
) -> None:
    key = (source_step, target_step, str(field) if field else None)
    if not source_step or not target_step or source_step == target_step or key in seen:
        return
    seen.add(key)
    transitions.append(
        {
            "source_step": source_step,
            "target_step": target_step,
            "source_tool": str(source_tool or ""),
            "target_tool": str(target_tool or ""),
            "relation": relation,
            "evidence_type": "observed" if observed else "planned",
            "field": str(field) if field else None,
            "path": _clean_path(path),
        }
    )


def _transition_observed(
    steps: dict[str, dict[str, Any]], source_step: str, target_step: str
) -> bool:
    observed_states = {"completed", "failed", "retrying", "running"}
    return (
        str((steps.get(source_step) or {}).get("status")) == "completed"
        and str((steps.get(target_step) or {}).get("status")) in observed_states
    )


def _flow_status(
    steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
    plan_steps: list[dict[str, Any]],
) -> str:
    event_types = {str(row.get("type") or "") for row in events}
    if "plan.aborted" in event_types or any(step.get("status") == "failed" for step in steps):
        return "failed"
    if "plan.completed" in event_types:
        return "completed"
    if plan_steps and steps and all(step.get("status") == "completed" for step in steps):
        return "completed"
    if any(step.get("status") in {"running", "retrying"} for step in steps):
        return "running"
    if plan_steps:
        return "planned"
    return "inferred"


def _plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        row = value.to_dict()
        return row if isinstance(row, dict) else {}
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {}


def _unique_strings(values: Any) -> list[str]:
    output: list[str] = []
    for value in values if isinstance(values, (list, tuple, set)) else []:
        item = str(value or "").strip()
        if item and item not in output:
            output.append(item)
    return output


def _clean_text(value: Any) -> str:
    return str(scrub_trace_payload(str(value or "")) or "")


def _clean_path(value: Any) -> str | None:
    path = _clean_text(value).strip()
    return path or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "DIRECTION_SOURCE_TO_TARGET",
    "DIRECTION_TARGET_TO_SOURCE",
    "DIRECTION_UNDIRECTED",
    "DIRECTION_UNKNOWN",
    "EXECUTION_FLOW_SCHEMA_VERSION",
    "FLOW_MODE_INFERRED",
    "FLOW_MODE_OBSERVED",
    "FLOW_MODE_PLANNED",
    "classify_execution_edge",
    "derive_execution_flow",
]
