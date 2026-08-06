# Trace Observability Contract

## Goal

The observability layer explains why graph-tool-call ranked, selected,
expanded, admitted, or omitted each tool. It is a product-neutral audit surface,
not a second ranking algorithm and not a store for raw API traffic.

## Contract

`TraceEnvelope.schema_version` is currently `1.0`. An envelope contains request
metadata and ordered `TraceSpan` rows. Each span contains bounded events and
`TraceDecision` rows. A decision cannot be constructed without at least one
machine-readable reason code.

Stable stages are:

- `retrieval`
- `target_selection`
- `dependency_closure`
- `schema_admission`
- `plan`
- `runner`

The adapters consume existing public return values. They do not rerun or alter
the engine:

| Engine output | Trace adapter |
|---|---|
| `retrieve_graphify(..., include_evidence=True)` | `record_retrieval_result` |
| `select_target_candidate(...)` | `record_selector_result` |
| `DependencyClosureResult` | `record_dependency_closure` |
| `ToolBundle` | `record_tool_bundle` |
| `Plan` | `record_plan` |
| `PlanRunner.run_stream()` events | `record_runner_events` |

## Replay boundary

`replay_trace()` validates a persisted envelope and reconstructs stage order,
latency, outcomes, rank transitions, and reason coverage. Replay does not call
an LLM or an external tool. This makes incident review deterministic even when
the original provider or API is unavailable.

## Data safety

All attributes, evidence, events, and decisions pass through
`scrub_trace_payload()` before serialization or export. The built-in adapters
project only decision evidence and do not retain raw arguments, request bodies,
response bodies, or result payloads. Host applications should store access to
trace files under the same controls used for API schemas because tool names and
field paths may still describe internal systems.

## OpenTelemetry

The core package remains dependency-free. The `observability` extra installs
only `opentelemetry-api`; the host application owns its SDK, exporter, sampling,
resource attributes, and backend configuration. `OpenTelemetryTraceExporter`
uses the configured tracer provider and emits one root span, stage spans, and a
`graph_tool_call.decision` event for each decision.

## Performance gate

Recording is opt-in and uses no network I/O. The contract test records 200
simple spans and requires less than 5 ms average overhead per span. Backend
export must happen under the host application's OpenTelemetry sampling and
batching policy.
