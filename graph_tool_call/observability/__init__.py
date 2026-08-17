"""Optional, zero-dependency observability for graph-tool-call pipelines."""

from .adapters import (
    record_dependency_closure,
    record_plan,
    record_retrieval_result,
    record_runner_events,
    record_selector_result,
    record_target_admission,
    record_tool_bundle,
)
from .otel import OpenTelemetryTraceExporter
from .recorder import TraceRecorder, TraceSpanRecorder, load_trace, replay_trace
from .schema import (
    STAGE_DEPENDENCY_CLOSURE,
    STAGE_PLAN,
    STAGE_RETRIEVAL,
    STAGE_RUNNER,
    STAGE_SCHEMA_ADMISSION,
    STAGE_TARGET_ADMISSION,
    STAGE_TARGET_SELECTION,
    TRACE_SCHEMA_VERSION,
    TraceDecision,
    TraceEnvelope,
    TraceEvent,
    TraceSpan,
)

__all__ = [
    "STAGE_DEPENDENCY_CLOSURE",
    "STAGE_PLAN",
    "STAGE_RETRIEVAL",
    "STAGE_RUNNER",
    "STAGE_SCHEMA_ADMISSION",
    "STAGE_TARGET_ADMISSION",
    "STAGE_TARGET_SELECTION",
    "TRACE_SCHEMA_VERSION",
    "TraceDecision",
    "TraceEnvelope",
    "TraceEvent",
    "TraceRecorder",
    "TraceSpan",
    "TraceSpanRecorder",
    "load_trace",
    "OpenTelemetryTraceExporter",
    "record_dependency_closure",
    "record_plan",
    "record_retrieval_result",
    "record_runner_events",
    "record_selector_result",
    "record_target_admission",
    "record_tool_bundle",
    "replay_trace",
]
