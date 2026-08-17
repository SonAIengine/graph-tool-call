"""Stable, secret-safe trace contracts for graph-tool-call decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.learning import scrub_trace_payload

TRACE_SCHEMA_VERSION = "1.0"

STAGE_RETRIEVAL = "retrieval"
STAGE_TARGET_ADMISSION = "target_admission"
STAGE_TARGET_SELECTION = "target_selection"
STAGE_DEPENDENCY_CLOSURE = "dependency_closure"
STAGE_SCHEMA_ADMISSION = "schema_admission"
STAGE_PLAN = "plan"
STAGE_RUNNER = "runner"


def _clean_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    clean = scrub_trace_payload(value or {})
    return clean if isinstance(clean, dict) else {}


def _clean_text(value: Any) -> str:
    clean = scrub_trace_payload(str(value or ""))
    return str(clean or "")


def _clean_reason_codes(values: list[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    for value in values:
        code = _clean_text(value).strip()
        if code and code not in output:
            output.append(code)
    return output


@dataclass(frozen=True)
class TraceDecision:
    """One machine-readable choice made inside a trace span."""

    subject: str
    outcome: str
    reason_codes: list[str]
    score: float | None = None
    rank_before: int | None = None
    rank_after: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.subject or "").strip():
            raise ValueError("trace decision subject must be non-empty")
        if not str(self.outcome or "").strip():
            raise ValueError("trace decision outcome must be non-empty")
        reason_codes = _clean_reason_codes(self.reason_codes)
        if not reason_codes:
            raise ValueError("trace decisions require at least one reason code")
        object.__setattr__(self, "subject", _clean_text(self.subject))
        object.__setattr__(self, "outcome", _clean_text(self.outcome))
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(self, "evidence", _clean_mapping(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "score": self.score,
            "rank_before": self.rank_before,
            "rank_after": self.rank_after,
            "evidence": _clean_mapping(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TraceDecision:
        return cls(
            subject=str(value.get("subject") or ""),
            outcome=str(value.get("outcome") or ""),
            reason_codes=[str(item) for item in (value.get("reason_codes") or [])],
            score=float(value["score"]) if value.get("score") is not None else None,
            rank_before=(
                int(value["rank_before"]) if value.get("rank_before") is not None else None
            ),
            rank_after=int(value["rank_after"]) if value.get("rank_after") is not None else None,
            evidence=value.get("evidence") if isinstance(value.get("evidence"), dict) else {},
        )


@dataclass(frozen=True)
class TraceEvent:
    """A bounded diagnostic event attached to a trace span."""

    name: str
    timestamp: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("trace event name must be non-empty")
        object.__setattr__(self, "name", _clean_text(self.name))
        object.__setattr__(self, "timestamp", str(self.timestamp))
        object.__setattr__(self, "attributes", _clean_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "attributes": _clean_mapping(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TraceEvent:
        return cls(
            name=str(value.get("name") or ""),
            timestamp=str(value.get("timestamp") or ""),
            attributes=(
                value.get("attributes") if isinstance(value.get("attributes"), dict) else {}
            ),
        )


@dataclass(frozen=True)
class TraceSpan:
    """A timed engine stage with decisions and bounded events."""

    span_id: str
    parent_span_id: str | None
    sequence: int
    stage: str
    name: str
    started_at: str
    ended_at: str
    duration_ms: float
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)
    decisions: list[TraceDecision] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.span_id or "").strip():
            raise ValueError("trace span_id must be non-empty")
        if not str(self.stage or "").strip() or not str(self.name or "").strip():
            raise ValueError("trace span stage and name must be non-empty")
        object.__setattr__(self, "stage", _clean_text(self.stage))
        object.__setattr__(self, "name", _clean_text(self.name))
        object.__setattr__(self, "status", _clean_text(self.status))
        object.__setattr__(self, "attributes", _clean_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(float(self.duration_ms), 6),
            "status": self.status,
            "attributes": _clean_mapping(self.attributes),
            "decisions": [item.to_dict() for item in self.decisions],
            "events": [item.to_dict() for item in self.events],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TraceSpan:
        return cls(
            span_id=str(value.get("span_id") or ""),
            parent_span_id=(str(value["parent_span_id"]) if value.get("parent_span_id") else None),
            sequence=int(value.get("sequence") or 0),
            stage=str(value.get("stage") or ""),
            name=str(value.get("name") or ""),
            started_at=str(value.get("started_at") or ""),
            ended_at=str(value.get("ended_at") or ""),
            duration_ms=float(value.get("duration_ms") or 0.0),
            status=str(value.get("status") or "ok"),
            attributes=(
                value.get("attributes") if isinstance(value.get("attributes"), dict) else {}
            ),
            decisions=[
                TraceDecision.from_dict(item)
                for item in (value.get("decisions") or [])
                if isinstance(item, dict)
            ],
            events=[
                TraceEvent.from_dict(item)
                for item in (value.get("events") or [])
                if isinstance(item, dict)
            ],
        )


@dataclass(frozen=True)
class TraceEnvelope:
    """Versioned trace payload safe for persistence and export."""

    trace_id: str
    operation: str
    started_at: str
    ended_at: str
    duration_ms: float
    status: str
    graph_tool_call_version: str
    attributes: dict[str, Any] = field(default_factory=dict)
    spans: list[TraceSpan] = field(default_factory=list)
    schema_version: str = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRACE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported trace schema version {self.schema_version!r}; "
                f"expected {TRACE_SCHEMA_VERSION!r}"
            )
        if not str(self.trace_id or "").strip() or not str(self.operation or "").strip():
            raise ValueError("trace_id and operation must be non-empty")
        object.__setattr__(self, "operation", _clean_text(self.operation))
        object.__setattr__(self, "status", _clean_text(self.status))
        object.__setattr__(self, "attributes", _clean_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "operation": self.operation,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round(float(self.duration_ms), 6),
            "status": self.status,
            "graph_tool_call_version": self.graph_tool_call_version,
            "attributes": _clean_mapping(self.attributes),
            "spans": [
                span.to_dict() for span in sorted(self.spans, key=lambda item: item.sequence)
            ],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TraceEnvelope:
        if not isinstance(value, dict):
            raise TypeError("trace payload must be a mapping")
        return cls(
            schema_version=str(value.get("schema_version") or ""),
            trace_id=str(value.get("trace_id") or ""),
            operation=str(value.get("operation") or ""),
            started_at=str(value.get("started_at") or ""),
            ended_at=str(value.get("ended_at") or ""),
            duration_ms=float(value.get("duration_ms") or 0.0),
            status=str(value.get("status") or "unknown"),
            graph_tool_call_version=str(value.get("graph_tool_call_version") or "unknown"),
            attributes=(
                value.get("attributes") if isinstance(value.get("attributes"), dict) else {}
            ),
            spans=[
                TraceSpan.from_dict(item)
                for item in (value.get("spans") or [])
                if isinstance(item, dict)
            ],
        )
