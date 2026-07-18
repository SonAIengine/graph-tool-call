"""Unified graphify edge helpers.

The helpers in this module normalize structural, LLM-curated, manual, and
run-observed signals into one additive edge shape. They operate on plain
dicts so callers can persist the result in JSON without depending on a graph
backend.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

EVIDENCE_STRUCTURAL = "structural"
EVIDENCE_NAME_BASED = "name_based"
EVIDENCE_PROVEN = "proven"
EVIDENCE_RUN = "run"
EVIDENCE_LLM_CURATED = "llm_curated"
EVIDENCE_MANUAL = "manual"

_DATA_FLOW_RELATIONS = frozenset({"requires", "precedes", "produces_for"})
_BINDING_RE = re.compile(r"^\$\{(\w+)\.(.+)\}$")


def normalize_graph_edge(
    edge: dict[str, Any],
    default_source: str = EVIDENCE_STRUCTURAL,
) -> dict[str, Any]:
    """Normalize an edge dict to the graphify v2 unified schema."""

    if edge.get("evidence_sources"):
        normalized = dict(edge)
        normalized.setdefault("kind", _infer_kind(normalized.get("relation")))
        normalized.setdefault("data_flow", None)
        normalized.setdefault("is_manual", False)
        normalized.setdefault("deleted_by_user", False)
        normalized["relation"] = _relation_value(normalized.get("relation"))
        normalized["confidence"] = _confidence_value(normalized.get("confidence") or "EXTRACTED")
        return normalized

    relation = _relation_value(edge.get("relation"))
    confidence = _confidence_value(edge.get("confidence") or "EXTRACTED")
    layer = edge.get("layer", 1)
    evidence_source = EVIDENCE_NAME_BASED if layer == 2 else default_source

    return {
        "source": edge.get("source"),
        "target": edge.get("target"),
        "relation": relation,
        "weight": float(edge.get("weight", 1.0) or 1.0),
        "confidence": confidence,
        "conf_score": float(edge.get("conf_score", 0.0) or 0.0),
        "evidence": edge.get("evidence") or "",
        "layer": layer,
        "kind": _infer_kind(relation),
        "evidence_sources": [evidence_source],
        "data_flow": edge.get("data_flow"),
        "is_manual": bool(edge.get("is_manual", False)),
        "deleted_by_user": bool(edge.get("deleted_by_user", False)),
    }


def merge_graph_edges(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge two unified edges for the same ``(source, target)`` pair."""

    left = normalize_graph_edge(existing)
    right = normalize_graph_edge(incoming)

    sources = list(left.get("evidence_sources") or [])
    for source in right.get("evidence_sources") or []:
        if source not in sources:
            sources.append(source)

    conf_score = max(float(left.get("conf_score") or 0.0), float(right.get("conf_score") or 0.0))
    if len(sources) > 1:
        conf_score = min(1.0, conf_score + 0.05 * (len(sources) - 1))

    evidence_notes: list[str] = []
    for item in (left, right):
        note = str(item.get("evidence") or "")
        if note and note not in evidence_notes:
            evidence_notes.append(note)

    merged = dict(left)
    merged.update(
        {
            "conf_score": conf_score,
            "evidence_sources": sources,
            "evidence": " | ".join(evidence_notes),
            "data_flow": right.get("data_flow") or left.get("data_flow"),
        }
    )
    if left.get("kind") == "data" or right.get("kind") == "data":
        merged["kind"] = "data"
        if EVIDENCE_PROVEN in (right.get("evidence_sources") or []):
            merged["relation"] = right.get("relation") or merged.get("relation")
    if left.get("is_manual") or right.get("is_manual"):
        merged["is_manual"] = True
    if left.get("deleted_by_user") or right.get("deleted_by_user"):
        merged["deleted_by_user"] = True
    return merged


def derive_plan_trace_edges(
    plan: Any,
    trace_steps: list[Any] | None = None,
    *,
    evidence_source: str = EVIDENCE_RUN,
) -> list[dict[str, Any]]:
    """Turn successful step bindings into run-observed graph edges."""

    plan_dict = _as_plain_dict(plan)
    steps = plan_dict.get("steps") or []
    if len(steps) < 2:
        return []

    step_tool = {s.get("id"): s.get("tool") for s in steps if isinstance(s, dict)}
    completed = _completed_step_ids(trace_steps)
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for step in steps:
        if not isinstance(step, dict):
            continue
        target_tool = step.get("tool")
        target_step_id = step.get("id")
        if not target_tool:
            continue
        if completed is not None and target_step_id not in completed:
            continue
        for field_name, value in (step.get("args") or {}).items():
            if not isinstance(value, str):
                continue
            match = _BINDING_RE.match(value.strip())
            if not match:
                continue
            source_step_id, path = match.group(1), match.group(2)
            if source_step_id in ("input", "user_input"):
                continue
            if completed is not None and source_step_id not in completed:
                continue
            source_tool = step_tool.get(source_step_id)
            if not source_tool or source_tool == target_tool:
                continue
            key = (str(source_tool), str(target_tool), str(field_name))
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": source_tool,
                    "target": target_tool,
                    "relation": "requires",
                    "weight": 1.0,
                    "confidence": "INFERRED",
                    "conf_score": 0.5,
                    "layer": 5,
                    "evidence": f"run-observed data flow: {source_step_id}.{path} -> {field_name}",
                    "kind": "data",
                    "evidence_sources": [evidence_source],
                    "data_flow": {
                        "from_path": path,
                        "to_field": field_name,
                        "observed_count": 1,
                    },
                    "is_manual": False,
                    "deleted_by_user": False,
                }
            )

    return edges


def _completed_step_ids(trace_steps: list[Any] | None) -> set[str] | None:
    if trace_steps is None:
        return None
    completed: set[str] = set()
    for step in trace_steps:
        row = _as_plain_dict(step)
        step_id = row.get("step_id") or row.get("id")
        status = str(row.get("status") or "").lower()
        error = row.get("error")
        if step_id and status in ("", "completed", "ok", "success", "done") and not error:
            completed.add(str(step_id))
    return completed


def _as_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}


def _relation_value(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else value
    return str(raw or "").lower()


def _confidence_value(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else value
    return str(raw or "")


def _infer_kind(relation: Any) -> str:
    return "data" if _relation_value(relation) in _DATA_FLOW_RELATIONS else "semantic"


__all__ = [
    "EVIDENCE_LLM_CURATED",
    "EVIDENCE_MANUAL",
    "EVIDENCE_NAME_BASED",
    "EVIDENCE_PROVEN",
    "EVIDENCE_RUN",
    "EVIDENCE_STRUCTURAL",
    "derive_plan_trace_edges",
    "merge_graph_edges",
    "normalize_graph_edge",
]
