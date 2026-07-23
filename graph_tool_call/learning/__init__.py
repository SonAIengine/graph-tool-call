"""Trace learning helpers for collection-scoped tool graph feedback.

The learning loop intentionally stores compact evidence, not raw API payloads.
It turns execution traces into suggestions that adapters can keep in shadow
mode first, then promote after repeated success or operator review.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

SUGGESTION_TARGET_PREFERENCE = "target_preference"
SUGGESTION_PLAN_PATH = "plan_path"
SUGGESTION_DATA_FLOW_EDGE = "data_flow_edge"
SUGGESTION_FIELD_MAPPING = "field_mapping"
SUGGESTION_CONTEXT_DEFAULT_CANDIDATE = "context_default_candidate"
SUGGESTION_ENUM_MAPPING_CANDIDATE = "enum_mapping_candidate"

SUGGESTION_TYPES = frozenset(
    {
        SUGGESTION_TARGET_PREFERENCE,
        SUGGESTION_PLAN_PATH,
        SUGGESTION_DATA_FLOW_EDGE,
        SUGGESTION_FIELD_MAPPING,
        SUGGESTION_CONTEXT_DEFAULT_CANDIDATE,
        SUGGESTION_ENUM_MAPPING_CANDIDATE,
    }
)

_SECRET_KEY_RE = re.compile(
    r"(authorization|cookie|token|api[_-]?key|secret|password|passwd|session|"
    r"x[-_]?user[-_]?id|user[_-]?id)",
    re.IGNORECASE,
)
_RAW_PAYLOAD_KEY_RE = re.compile(
    r"^(raw_)?(request|response)?_?body$|^(raw|payload|output|result)$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d -]{7,}\d)\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+\b", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_HEX_SECRET_RE = re.compile(r"\b[a-f0-9]{32,}\b", re.IGNORECASE)
_MAX_ATTEMPTS = 50
_MAX_SUGGESTIONS = 100


def scrub_trace_payload(value: Any, *, max_string: int = 240) -> Any:
    """Return a JSON-safe value with secrets and raw payloads redacted."""

    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _SECRET_KEY_RE.search(key_str) or _RAW_PAYLOAD_KEY_RE.search(key_str):
                clean[key_str] = "[REDACTED]"
            else:
                clean[key_str] = scrub_trace_payload(item, max_string=max_string)
        return clean
    if isinstance(value, list):
        return [scrub_trace_payload(item, max_string=max_string) for item in value[:100]]
    if isinstance(value, tuple):
        return [scrub_trace_payload(item, max_string=max_string) for item in value[:100]]
    if isinstance(value, str):
        redacted = _BEARER_RE.sub("[REDACTED]", value)
        redacted = _JWT_RE.sub("[REDACTED]", redacted)
        redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
        redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
        redacted = _HEX_SECRET_RE.sub("[REDACTED]", redacted)
        if len(redacted) > max_string:
            return redacted[:max_string].rstrip() + "..."
        return redacted
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return scrub_trace_payload(str(value), max_string=max_string)


def build_trace_learning_record(
    *,
    query: str,
    collection_id: str = "",
    attempt_id: str | None = None,
    session_id: str | None = None,
    selected_target: str | None = None,
    llm_target: str | None = None,
    plan: Any | None = None,
    plan_tools: list[str] | None = None,
    failure_reason: str | None = None,
    success: bool | None = None,
    latency_ms: int | float | None = None,
    target_selector: dict[str, Any] | None = None,
    trace_edges: list[dict[str, Any]] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a compact, persistence-ready execution learning record."""

    normalized_query = normalize_query_family(query)
    tools = list(plan_tools or _plan_tools(plan))
    clean_target_selector = scrub_trace_payload(target_selector or {})
    clean_trace_edges = [
        scrub_trace_payload(edge)
        for edge in (trace_edges or [])
        if isinstance(edge, dict) and edge.get("source") and edge.get("target")
    ]
    clean_failure = scrub_trace_payload(failure_reason) if failure_reason else None
    resolved_success = bool(success) if success is not None else not bool(clean_failure)
    return {
        "query": scrub_trace_payload(query),
        "query_fingerprint": stable_hash(normalized_query),
        "query_family": normalized_query,
        "collection_id": str(collection_id or ""),
        "attempt_id": str(attempt_id or stable_hash(f"{collection_id}:{query}:{created_at or ''}")),
        "session_id_hash": stable_hash(session_id or "") if session_id else None,
        "selected_target": str(selected_target or ""),
        "llm_target": str(llm_target or "") or None,
        "plan_tools": tools,
        "failure_reason": clean_failure,
        "success": resolved_success,
        "latency_ms": int(latency_ms) if latency_ms is not None else None,
        "target_selector": clean_target_selector,
        "trace_edges": clean_trace_edges,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }


def derive_learning_suggestions(
    record: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    existing_suggestions: list[dict[str, Any]] | None = None,
    promotion_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Derive collection-scoped suggestions from one learning record."""

    if not record or not record.get("success"):
        return []
    policy = _promotion_policy(promotion_policy)
    base_history = [row for row in (history or []) if isinstance(row, dict)]
    prior_failures = _prior_failure_count(record, base_history)
    suggestions = []
    selected_target = str(record.get("selected_target") or "")
    plan_tools = [str(name) for name in (record.get("plan_tools") or []) if name]
    base = _base_suggestion(record, prior_failures=prior_failures)

    if selected_target:
        suggestions.append(
            {
                **base,
                "id": _suggestion_id(record, SUGGESTION_TARGET_PREFERENCE, selected_target),
                "type": SUGGESTION_TARGET_PREFERENCE,
                "target": selected_target,
                "evidence": {
                    "selected_target": selected_target,
                    "llm_target": record.get("llm_target"),
                    "target_selector": scrub_trace_payload(record.get("target_selector") or {}),
                },
            }
        )
    if plan_tools:
        plan_key = " -> ".join(plan_tools)
        suggestions.append(
            {
                **base,
                "id": _suggestion_id(record, SUGGESTION_PLAN_PATH, plan_key),
                "type": SUGGESTION_PLAN_PATH,
                "target": plan_tools[-1],
                "plan_tools": plan_tools,
                "evidence": {"plan_tools": plan_tools},
            }
        )
    for edge in record.get("trace_edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        to_field = str((edge.get("data_flow") or {}).get("to_field") or "")
        if not source or not target:
            continue
        key = f"{source}->{target}:{to_field}"
        suggestions.append(
            {
                **base,
                "id": _suggestion_id(record, SUGGESTION_DATA_FLOW_EDGE, key),
                "type": SUGGESTION_DATA_FLOW_EDGE,
                "target": target,
                "edge": scrub_trace_payload(edge),
                "evidence": {"edge": scrub_trace_payload(edge)},
            }
        )

    merged = merge_learning_suggestions(
        list(existing_suggestions or []),
        suggestions,
        history=[*base_history, record],
        promotion_policy=policy,
    )
    incoming_ids = {item["id"] for item in suggestions}
    return [item for item in merged if item.get("id") in incoming_ids]


def apply_learning_suggestions(
    query: str,
    candidates: list[str] | list[dict[str, Any]],
    suggestions: list[dict[str, Any]] | None,
    *,
    mode: str = "promoted",
    max_boost: float = 0.06,
) -> dict[str, Any]:
    """Return candidate rows with low-weight learning boosts and traceable signals."""

    candidate_rows = _candidate_rows(candidates)
    signals = learning_signal_map(query, suggestions or [], mode=mode, max_boost=max_boost)
    adjusted: list[dict[str, Any]] = []
    for row in candidate_rows:
        name = str(row.get("name") or "")
        signal = signals.get(name) or {}
        score = float(row.get("score") or row.get("final_score") or 0.0)
        boosted = score + float(signal.get("score") or 0.0)
        new_row = dict(row)
        new_row["score"] = boosted
        if signal:
            new_row["learning"] = signal
        adjusted.append(new_row)
    return {
        "candidates": adjusted,
        "signals": list(signals.values()),
        "applied_count": len(signals),
        "mode": mode,
    }


def merge_learning_suggestions(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    history: list[dict[str, Any]] | None = None,
    promotion_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Merge suggestions by id while updating observation counts and status."""

    policy = _promotion_policy(promotion_policy)
    by_id = {str(item.get("id") or ""): dict(item) for item in existing if item.get("id")}
    for suggestion in incoming:
        sid = str(suggestion.get("id") or "")
        if not sid:
            continue
        previous = by_id.get(sid) or {}
        merged = {**previous, **suggestion}
        observations = int(previous.get("observations") or 0) + int(
            suggestion.get("observations") or 1
        )
        merged["observations"] = observations
        merged["last_seen_at"] = suggestion.get("last_seen_at") or suggestion.get("created_at")
        if previous.get("status") == "promoted":
            merged["status"] = "promoted"
        elif previous.get("status") == "rejected":
            merged["status"] = "rejected"
        else:
            merged["status"] = _suggestion_status(merged, history or [], policy)
        by_id[sid] = merged
    ordered = sorted(
        by_id.values(),
        key=lambda item: (str(item.get("status") or ""), str(item.get("last_seen_at") or "")),
        reverse=True,
    )
    return ordered[: int(policy["max_suggestions"])]


def summarize_learning_state(learning: dict[str, Any] | None) -> dict[str, Any]:
    """Build a small UI/API summary for a collection learning block."""

    data = learning if isinstance(learning, dict) else {}
    attempts = [row for row in data.get("attempts") or [] if isinstance(row, dict)]
    suggestions = [row for row in data.get("suggestions") or [] if isinstance(row, dict)]
    success_count = sum(1 for row in attempts if row.get("success"))
    return {
        "attempt_count": len(attempts),
        "success_count": success_count,
        "failure_count": len(attempts) - success_count,
        "success_rate": round(success_count / len(attempts), 4) if attempts else None,
        "suggestion_count": len(suggestions),
        "suggested_count": sum(1 for row in suggestions if row.get("status") == "suggested"),
        "promotable_count": sum(1 for row in suggestions if row.get("status") == "promotable"),
        "promoted_count": sum(1 for row in suggestions if row.get("status") == "promoted"),
        "rejected_count": sum(1 for row in suggestions if row.get("status") == "rejected"),
    }


def learning_signal_map(
    query: str,
    suggestions: list[dict[str, Any]],
    *,
    mode: str = "promoted",
    max_boost: float = 0.06,
) -> dict[str, dict[str, Any]]:
    """Return selector/retrieval boosts keyed by target tool name."""

    query_fp = stable_hash(normalize_query_family(query))
    accepted_statuses = (
        {"promoted"} if mode == "promoted" else {"promoted", "promotable", "suggested"}
    )
    signals: dict[str, dict[str, Any]] = {}
    for suggestion in suggestions or []:
        if not isinstance(suggestion, dict):
            continue
        if suggestion.get("status") not in accepted_statuses:
            continue
        if suggestion.get("query_fingerprint") != query_fp:
            continue
        target = str(suggestion.get("target") or "")
        if not target:
            continue
        obs = max(1, int(suggestion.get("observations") or 1))
        score = min(float(max_boost), 0.025 + 0.01 * min(obs - 1, 3))
        current = signals.get(target)
        if current and float(current.get("score") or 0.0) >= score:
            continue
        signals[target] = {
            "source": "learning",
            "target": target,
            "suggestion_id": suggestion.get("id"),
            "suggestion_type": suggestion.get("type"),
            "status": suggestion.get("status"),
            "observations": obs,
            "score": round(score, 6),
        }
    return signals


def normalize_query_family(query: str) -> str:
    """Normalize a natural-language query for collection-local trace grouping."""

    text = str(query or "").strip().lower()
    text = re.sub(r"[\w.+-]+@[\w.-]+", " ", text)
    text = re.sub(r"\b\d{2,}\b", " <num> ", text)
    text = re.sub(r"\s+", " ", re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)).strip()
    return text


def stable_hash(value: str) -> str:
    """Short stable SHA-256 digest for non-secret identifiers."""

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _base_suggestion(record: dict[str, Any], *, prior_failures: int) -> dict[str, Any]:
    return {
        "query_fingerprint": record.get("query_fingerprint"),
        "query_family": record.get("query_family"),
        "collection_id": record.get("collection_id") or "",
        "status": "suggested",
        "observations": 1,
        "prior_failure_count": prior_failures,
        "created_at": record.get("created_at"),
        "last_seen_at": record.get("created_at"),
        "evidence_sources": ["run"],
    }


def _suggestion_id(record: dict[str, Any], suggestion_type: str, key: str) -> str:
    basis = "|".join(
        [
            str(record.get("collection_id") or ""),
            str(record.get("query_fingerprint") or ""),
            suggestion_type,
            key,
        ]
    )
    return f"{suggestion_type}:{stable_hash(basis)}"


def _suggestion_status(
    suggestion: dict[str, Any],
    history: list[dict[str, Any]],
    policy: dict[str, Any],
) -> str:
    if int(suggestion.get("observations") or 0) >= int(policy["min_success_observations"]):
        return "promotable"
    success_count = _matching_success_count(suggestion, history)
    failure_count = _matching_failure_count(suggestion, history)
    total = success_count + failure_count
    failure_ratio = failure_count / total if total else 0.0
    if success_count >= int(policy["min_success_observations"]) and failure_ratio <= float(
        policy["max_recent_failure_ratio"]
    ):
        return "promotable"
    return "suggested"


def _matching_success_count(suggestion: dict[str, Any], history: list[dict[str, Any]]) -> int:
    return sum(
        1
        for record in history
        if record.get("success") and _record_matches_suggestion(record, suggestion)
    )


def _matching_failure_count(suggestion: dict[str, Any], history: list[dict[str, Any]]) -> int:
    return sum(
        1
        for record in history
        if not record.get("success") and _record_matches_suggestion(record, suggestion)
    )


def _record_matches_suggestion(record: dict[str, Any], suggestion: dict[str, Any]) -> bool:
    if record.get("query_fingerprint") != suggestion.get("query_fingerprint"):
        return False
    target = str(suggestion.get("target") or "")
    if not target:
        return True
    if str(record.get("selected_target") or "") == target:
        return True
    return target in [str(name) for name in (record.get("plan_tools") or [])]


def _prior_failure_count(record: dict[str, Any], history: list[dict[str, Any]]) -> int:
    query_fp = record.get("query_fingerprint")
    return sum(
        1 for row in history if row.get("query_fingerprint") == query_fp and not row.get("success")
    )


def _promotion_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    out = {
        "min_success_observations": 2,
        "max_recent_failure_ratio": 0.5,
        "max_attempts": _MAX_ATTEMPTS,
        "max_suggestions": _MAX_SUGGESTIONS,
    }
    if isinstance(policy, dict):
        for key in out:
            if key in policy:
                out[key] = policy[key]
    return out


def _plan_tools(plan: Any | None) -> list[str]:
    if plan is None:
        return []
    if hasattr(plan, "__dict__") and not isinstance(plan, dict):
        plan = {
            "steps": [getattr(step, "__dict__", step) for step in getattr(plan, "steps", []) or []]
        }
    if not isinstance(plan, dict):
        return []
    tools: list[str] = []
    for step in plan.get("steps") or []:
        if isinstance(step, dict) and step.get("tool"):
            tools.append(str(step["tool"]))
    return tools


def _candidate_rows(candidates: list[str] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in candidates or []:
        if isinstance(item, dict):
            name = str(
                item.get("name") or item.get("tool") or item.get("target") or item.get("id") or ""
            )
            row = dict(item)
            row["name"] = name
        else:
            row = {"name": str(item), "score": 0.0}
        if row.get("name"):
            rows.append(row)
    return rows


__all__ = [
    "SUGGESTION_CONTEXT_DEFAULT_CANDIDATE",
    "SUGGESTION_DATA_FLOW_EDGE",
    "SUGGESTION_ENUM_MAPPING_CANDIDATE",
    "SUGGESTION_FIELD_MAPPING",
    "SUGGESTION_PLAN_PATH",
    "SUGGESTION_TARGET_PREFERENCE",
    "SUGGESTION_TYPES",
    "apply_learning_suggestions",
    "build_trace_learning_record",
    "derive_learning_suggestions",
    "learning_signal_map",
    "merge_learning_suggestions",
    "normalize_query_family",
    "scrub_trace_payload",
    "stable_hash",
    "summarize_learning_state",
]
