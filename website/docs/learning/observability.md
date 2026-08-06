---
title: Trace Observability
description: Replay retrieval, selection, dependency, and token-budget decisions with optional OpenTelemetry export.
sidebar_position: 5
---

# Trace observability

When a catalog returns the wrong tools, the useful question is not only “what
ranked first?” It is also:

- which score channels moved each candidate;
- whether the LLM target was preserved or overridden;
- which prerequisite producers were expanded;
- which schemas fit the model token budget;
- and which stage consumed the latency.

The observability API records those answers in one versioned, secret-scrubbed
trace. It does not change the engine result.

## Record a pipeline

```python
from graph_tool_call.graphify import (
    assemble_tool_bundle,
    retrieve_graphify,
    select_target_candidate,
)
from graph_tool_call.observability import (
    STAGE_RETRIEVAL,
    STAGE_SCHEMA_ADMISSION,
    STAGE_TARGET_SELECTION,
    TraceRecorder,
    record_retrieval_result,
    record_selector_result,
    record_tool_bundle,
)

trace = TraceRecorder("catalog_request", attributes={"query": query})

with trace.start_span(STAGE_RETRIEVAL, "retrieve_graphify") as span:
    retrieval = retrieve_graphify(graph, query, top_k=8, include_evidence=True)
    record_retrieval_result(span, retrieval)

with trace.start_span(STAGE_TARGET_SELECTION, "select_target_candidate") as span:
    selection = select_target_candidate(
        query,
        [row["name"] for row in retrieval["results"]],
        graph.tools,
        retrieval_results=retrieval["results"],
    )
    record_selector_result(span, selection)

with trace.start_span(STAGE_SCHEMA_ADMISSION, "assemble_tool_bundle") as span:
    bundle = assemble_tool_bundle(
        query,
        selection["selected_target"],
        graph.tools,
        graph=graph,
        token_budget=2048,
    )
    record_tool_bundle(span, bundle)

trace.write("trace.json")
```

Each candidate or schema decision has an `outcome`, rank/score fields when
available, evidence, and at least one `reason_code`.

## Replay safely

```bash
graph-tool-call trace trace.json
graph-tool-call trace trace.json --json
```

Replay validates schema version `1.0` and reconstructs stage order, stage
latency, decision outcomes, and reason coverage. It never calls an LLM or an
external API.

The common scrub policy redacts credential-like keys, bearer/JWT-like values,
raw body/payload/result fields, email addresses, and phone-like values. The
built-in plan and runner adapters intentionally omit raw arguments and outputs.

## Export to OpenTelemetry

```bash
pip install "graph-tool-call[observability]"
```

```python
from graph_tool_call.observability import OpenTelemetryTraceExporter

OpenTelemetryTraceExporter().export(trace.finish())
```

Configure the OpenTelemetry SDK, sampling, batching, and backend in the host
application. graph-tool-call installs only the API and uses the active tracer
provider, so it does not choose your collector or telemetry vendor.

## What to store

Store scrubbed trace JSON, not raw HTTP request/response objects. Tool names and
field paths can still reveal internal API structure, so apply the same access
controls and retention policy used for catalog artifacts.
