---
title: Public API
description: Stable imports and adapter-safe contracts for graph-tool-call.
---

# Public API

This page lists the public modules and entry points that application adapters
should rely on. Everything here is designed for product integrations that need
stable imports across graph-tool-call releases.

Avoid importing private helpers from implementation modules unless another
reference page explicitly marks them as stable.

## Import Policy

| Import Path | Stability | Use It For |
| --- | --- | --- |
| `graph_tool_call` | stable | Core package exports such as `ToolGraph` and `ToolSchema` |
| `graph_tool_call.graphify` | stable | OpenAPI collection artifacts, retrieval, target selection, graph edges |
| `graph_tool_call.plan` | stable | Plan synthesis, plan schemas, runner events |
| `graph_tool_call.learning` | stable | Scrubbed trace learning records and suggestions |
| `graph_tool_call.analyze` | stable | OpenAPI readiness and graph diagnostics |
| `graph_tool_call.ingest.*` | internal unless documented | Low-level ingestion implementation details |
| `graph_tool_call.graphify.*` submodules | internal unless documented | Implementation helpers behind public graphify exports |

## Core Objects

```python
from graph_tool_call import ToolGraph, ToolSchema
```

`ToolGraph` is the main facade for small and medium-sized in-process use. It can
ingest OpenAPI specs, search tools, analyze graph quality, export visualizations,
and execute OpenAPI tools through the built-in HTTP executor.

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

tools = graph.retrieve("find pets by status", top_k=8)
ranked = graph.retrieve_with_scores("find pets by status", top_k=8)
report = graph.analyze()
```

`ToolSchema` is the normalized representation shared by ingestion, graph build,
retrieval, planning, and adapters.

```python
from graph_tool_call import ToolSchema

tool = ToolSchema(
    name="getCustomerOrders",
    description="Find orders for a customer",
)
```

When you already have OpenAI, Anthropic, or MCP tool definitions, prefer the
public parser:

```python
from graph_tool_call import parse_tool

tool = parse_tool(
    {
        "name": "getCustomerOrders",
        "description": "Find orders for a customer",
        "parameters": {
            "type": "object",
            "required": ["customerId"],
            "properties": {"customerId": {"type": "string"}},
        },
    }
)
```

## Graphify APIs

Use graphify APIs when the caller stores or rebuilds large tool catalog
artifacts. These APIs are product-neutral: they do not know about databases,
cookies, user ids, UI state, or downstream auth tokens.

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    expand_candidates_with_producers,
    ingest_openapi_graphify,
    retrieve_graphify,
    select_target_candidate,
)
from graph_tool_call.graphify import (
    build_io_contract,
    derive_plan_trace_edges,
    merge_graph_edges,
    normalize_graph_edge,
)
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index
```

### Build A Collection Artifact

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

### Search A Persisted Artifact

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    artifact,
    query="refund-ready order list",
    top_k=8,
    include_evidence=True,
)

for result in response["results"]:
    print(result["tool_name"], result["score_breakdown"])
```

### Guard An LLM Target

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="refund-ready order list",
    candidates=[row["tool_name"] for row in response["results"]],
    tools=artifact["tools"],
    retrieval_results=response["results"],
    llm_target="getOrderDetail",
)

print(selection["selected_target"])
print(selection["overrode_llm"])
print(selection["reason_codes"])
```

## Plan APIs

The `plan` package is transport-agnostic. The engine synthesizes or runs a plan;
the adapter decides how a tool is actually called.

```python
from graph_tool_call.plan import (
    PathSynthesizer,
    Plan,
    PlanRunner,
    PlanStep,
    PlanSynthesisError,
    parse_intent,
    synthesize_failure_response,
    synthesize_success_response,
)
```

### Run A Plan

```python
from dataclasses import asdict

from graph_tool_call.plan import Plan, PlanRunner, PlanStep

plan = Plan(
    id="plan-1",
    goal="Find an order and return detail",
    steps=[
        PlanStep(id="s1", tool="searchOrders", args={"keyword": "A-100"}),
        PlanStep(id="s2", tool="getOrderDetail", args={"orderId": "${s1.items.0.id}"}),
    ],
)

def call_tool(name: str, args: dict):
    return executor.call(name, args)

runner = PlanRunner(call_tool)

for event in runner.run_stream(plan, trace_metadata={"collection_id": "orders"}):
    print(asdict(event))
```

## Learning APIs

Learning APIs store compact evidence from previous attempts. They never require
fine-tuning an LLM and should not persist raw request or response bodies.

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
)
```

```python
record = build_trace_learning_record(
    query="find refund-ready orders",
    collection_id="bo-dev",
    attempt_id="attempt-001",
    selected_target="getRefundableOrders",
    plan_tools=["searchOrders", "getRefundableOrders"],
    success=True,
    latency_ms=1430,
)

suggestions = derive_learning_suggestions(record)
```

## Analyze APIs

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection(
    "openapi.json",
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
)

print(report.to_dict()["summary"])
```

Use readiness reports before enabling search, plan, or execute flows for a
collection. The report is deterministic and safe to store in product metadata.

## Adapter Boundary

Keep these responsibilities outside graph-tool-call:

| Adapter Responsibility | Why |
| --- | --- |
| Database reads/writes | Storage shape and tenancy are product-specific |
| User authentication | The engine must not store live credentials |
| Session headers and cookies | Runtime auth belongs to the caller |
| SSE/UI forwarding | Event transport is product-specific |
| HTTP retry policy beyond `PlanRunner` options | Downstream semantics differ by product |
| Manual operator overrides | Store them in product metadata, pass them as options |

## Compatibility Rules

- Public APIs should add fields instead of changing existing shapes.
- Collection graph artifacts should remain readable across minor versions.
- Adapters should preserve unknown fields when rebuilding stored artifacts.
- Secrets, raw tokens, cookies, and user identifiers should not be written to
  artifact, report, learning, or event payloads.

## Related Pages

- [CLI](./cli.md)
- [Artifact Schemas](./artifact-schemas.md)
- [Event Schemas](./event-schemas.md)
- [Report Schemas](./report-schemas.md)
- [Compatibility](./compatibility.md)
