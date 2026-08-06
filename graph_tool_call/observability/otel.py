"""Optional OpenTelemetry export for stable graph-tool-call traces."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from graph_tool_call.learning import scrub_trace_payload

from .schema import TraceEnvelope


class OpenTelemetryTraceExporter:
    """Export a :class:`TraceEnvelope` through a configured OTel tracer.

    Importing this module has no third-party dependency. OpenTelemetry is loaded
    only when ``export()`` is called.
    """

    def __init__(self, tracer: Any | None = None, *, instrumentation_name: str = "graph-tool-call"):
        self._tracer = tracer
        self.instrumentation_name = instrumentation_name

    def export(self, value: TraceEnvelope | dict[str, Any]) -> None:
        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.trace import Status, StatusCode
        except ImportError as exc:  # pragma: no cover - exercised without the extra
            raise RuntimeError(
                "OpenTelemetry export requires `pip install graph-tool-call[observability]`."
            ) from exc

        trace = value if isinstance(value, TraceEnvelope) else TraceEnvelope.from_dict(value)
        tracer = self._tracer or otel_trace.get_tracer(self.instrumentation_name)
        root_attributes = _otel_attributes(
            {
                "schema_version": trace.schema_version,
                "status": trace.status,
                "graph_tool_call_version": trace.graph_tool_call_version,
                **trace.attributes,
            }
        )
        root_attributes["graph_tool_call.trace_id"] = trace.trace_id
        root = tracer.start_span(
            f"graph-tool-call.{trace.operation}",
            start_time=_timestamp_ns(trace.started_at),
            attributes=root_attributes,
        )
        span_objects: dict[str, Any] = {}
        try:
            for span in sorted(trace.spans, key=lambda item: item.sequence):
                parent = span_objects.get(span.parent_span_id) or root
                context = otel_trace.set_span_in_context(parent)
                exported = tracer.start_span(
                    span.name,
                    context=context,
                    start_time=_timestamp_ns(span.started_at),
                    attributes=_otel_attributes(
                        {
                            "stage": span.stage,
                            "status": span.status,
                            "sequence": span.sequence,
                            **span.attributes,
                        }
                    ),
                )
                for decision in span.decisions:
                    exported.add_event(
                        "graph_tool_call.decision",
                        attributes=_otel_attributes(decision.to_dict()),
                    )
                for event in span.events:
                    exported.add_event(
                        event.name,
                        attributes=_otel_attributes(event.attributes),
                        timestamp=_timestamp_ns(event.timestamp),
                    )
                exported.set_status(
                    Status(StatusCode.ERROR if span.status == "error" else StatusCode.OK)
                )
                exported.end(end_time=_timestamp_ns(span.ended_at))
                span_objects[span.span_id] = exported
            root.set_status(Status(StatusCode.ERROR if trace.status == "error" else StatusCode.OK))
        finally:
            root.end(end_time=_timestamp_ns(trace.ended_at))


def _timestamp_ns(value: str) -> int | None:
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)
    except (TypeError, ValueError):
        return None


def _otel_attributes(values: dict[str, Any]) -> dict[str, Any]:
    clean = scrub_trace_payload(values)
    if not isinstance(clean, dict):
        return {}
    output: dict[str, Any] = {}
    for key, value in clean.items():
        attr_key = f"graph_tool_call.{key}"
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            output[attr_key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (str, bool, int, float)) for item in value
        ):
            output[attr_key] = list(value)
        else:
            output[attr_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return output
