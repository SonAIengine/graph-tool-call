"""Low-overhead per-request trace recording and replay."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_tool_call import __version__
from graph_tool_call.learning import scrub_trace_payload

from .schema import TraceDecision, TraceEnvelope, TraceEvent, TraceSpan


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TraceSpanRecorder:
    """Mutable span handle created by :class:`TraceRecorder`."""

    def __init__(
        self,
        recorder: TraceRecorder,
        *,
        span_id: str,
        parent_span_id: str | None,
        sequence: int,
        stage: str,
        name: str,
        attributes: dict[str, Any] | None,
    ) -> None:
        self._recorder = recorder
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.sequence = sequence
        self.stage = str(stage)
        self.name = str(name)
        self.started_at = _utc_now()
        self._started_tick = time.perf_counter()
        self.attributes = _safe_mapping(attributes)
        self.decisions: list[TraceDecision] = []
        self.events: list[TraceEvent] = []
        self.status = "ok"
        self._finished = False

    def __enter__(self) -> TraceSpanRecorder:
        self._recorder._activate(self)
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc is not None:
            self.status = "error"
            self.event(
                "exception",
                {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
        self.finish()
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[str(key)] = scrub_trace_payload(value)

    def set_status(self, status: str) -> None:
        self.status = str(status or "unknown")

    def decision(
        self,
        subject: str,
        outcome: str,
        reason_codes: list[str] | tuple[str, ...],
        *,
        score: float | None = None,
        rank_before: int | None = None,
        rank_after: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> TraceDecision:
        item = TraceDecision(
            subject=subject,
            outcome=outcome,
            reason_codes=list(reason_codes),
            score=score,
            rank_before=rank_before,
            rank_after=rank_after,
            evidence=_safe_mapping(evidence),
        )
        self.decisions.append(item)
        return item

    def event(self, name: str, attributes: dict[str, Any] | None = None) -> TraceEvent:
        item = TraceEvent(
            name=name,
            timestamp=_utc_now().isoformat(),
            attributes=_safe_mapping(attributes),
        )
        self.events.append(item)
        return item

    def finish(self, status: str | None = None) -> TraceSpan:
        if self._finished:
            return self._recorder._span_by_id(self.span_id)
        if status:
            self.status = str(status)
        ended_at = _utc_now()
        duration_ms = max(0.0, (time.perf_counter() - self._started_tick) * 1000.0)
        span = TraceSpan(
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            sequence=self.sequence,
            stage=self.stage,
            name=self.name,
            started_at=self.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_ms=duration_ms,
            status=self.status,
            attributes=self.attributes,
            decisions=list(self.decisions),
            events=list(self.events),
        )
        self._finished = True
        self._recorder._complete(self, span)
        return span


class TraceRecorder:
    """Collect scrubbed stage spans for one graph-tool-call request."""

    def __init__(
        self,
        operation: str,
        *,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if not str(operation or "").strip():
            raise ValueError("trace operation must be non-empty")
        self.operation = str(operation)
        self.trace_id = str(trace_id or uuid.uuid4())
        self.attributes = _safe_mapping(attributes)
        self.started_at = _utc_now()
        self._started_tick = time.perf_counter()
        self._spans: list[TraceSpan] = []
        self._active: list[TraceSpanRecorder] = []
        self._sequence = 0
        self._finished: TraceEnvelope | None = None

    def start_span(
        self,
        stage: str,
        name: str | None = None,
        *,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceSpanRecorder:
        if self._finished is not None:
            raise RuntimeError("cannot add spans to a finished trace")
        if not str(stage or "").strip():
            raise ValueError("trace span stage must be non-empty")
        self._sequence += 1
        resolved_parent = parent_span_id
        if resolved_parent is None and self._active:
            resolved_parent = self._active[-1].span_id
        return TraceSpanRecorder(
            self,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=resolved_parent,
            sequence=self._sequence,
            stage=str(stage),
            name=str(name or stage),
            attributes=attributes,
        )

    def finish(self, status: str | None = None) -> TraceEnvelope:
        if self._finished is not None:
            return self._finished
        if self._active:
            raise RuntimeError("cannot finish trace while spans are active")
        ended_at = _utc_now()
        resolved_status = status or (
            "error" if any(span.status == "error" for span in self._spans) else "ok"
        )
        self._finished = TraceEnvelope(
            trace_id=self.trace_id,
            operation=self.operation,
            started_at=self.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_ms=max(0.0, (time.perf_counter() - self._started_tick) * 1000.0),
            status=str(resolved_status),
            graph_tool_call_version=__version__,
            attributes=self.attributes,
            spans=list(self._spans),
        )
        return self._finished

    def to_dict(self, *, status: str | None = None) -> dict[str, Any]:
        return self.finish(status=status).to_dict()

    def write(self, path: str | Path, *, status: str | None = None) -> Path:
        destination = Path(path)
        destination.write_text(
            json.dumps(self.to_dict(status=status), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination

    def _activate(self, span: TraceSpanRecorder) -> None:
        if span not in self._active:
            self._active.append(span)

    def _complete(self, handle: TraceSpanRecorder, span: TraceSpan) -> None:
        self._active = [item for item in self._active if item is not handle]
        self._spans.append(span)

    def _span_by_id(self, span_id: str) -> TraceSpan:
        for span in self._spans:
            if span.span_id == span_id:
                return span
        raise RuntimeError(f"trace span {span_id!r} has not been completed")


def load_trace(path: str | Path) -> TraceEnvelope:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("trace file must contain a JSON object")
    return TraceEnvelope.from_dict(payload)


def replay_trace(value: TraceEnvelope | dict[str, Any]) -> dict[str, Any]:
    """Validate and summarize a scrubbed trace without rerunning external tools."""

    trace = value if isinstance(value, TraceEnvelope) else TraceEnvelope.from_dict(value)
    decisions = [
        {
            "stage": span.stage,
            "span": span.name,
            **decision.to_dict(),
        }
        for span in sorted(trace.spans, key=lambda item: item.sequence)
        for decision in span.decisions
    ]
    outcomes: dict[str, list[str]] = {}
    for decision in decisions:
        outcomes.setdefault(str(decision["outcome"]), []).append(str(decision["subject"]))
    replay = scrub_trace_payload(
        {
            "schema_version": trace.schema_version,
            "trace_id": trace.trace_id,
            "operation": trace.operation,
            "status": trace.status,
            "duration_ms": trace.duration_ms,
            "stage_order": [
                span.stage for span in sorted(trace.spans, key=lambda item: item.sequence)
            ],
            "stage_durations_ms": {
                f"{span.sequence}:{span.stage}": span.duration_ms
                for span in sorted(trace.spans, key=lambda item: item.sequence)
            },
            "decision_count": len(decisions),
            "reason_coverage": (
                sum(bool(item.get("reason_codes")) for item in decisions) / len(decisions)
                if decisions
                else 1.0
            ),
            "outcomes": outcomes,
            "decisions": decisions,
        }
    )
    if not isinstance(replay, dict):
        raise TypeError("trace replay must produce a mapping")
    # W3C/OpenTelemetry trace IDs are 32 hexadecimal characters. They are
    # structural correlation IDs, so preserve them after generic secret scrub.
    replay["trace_id"] = trace.trace_id
    return replay


def _safe_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    clean = scrub_trace_payload(value or {})
    return clean if isinstance(clean, dict) else {}
