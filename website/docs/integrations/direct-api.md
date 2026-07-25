---
title: Direct API
description: Call graph-tool-call directly from application code without a framework adapter.
---

# Direct API

Use the direct API when you want full control over ingest, retrieval, target
selection, planning, and execution. This is the best integration style for
backend services that already own auth, DB access, logging, and HTTP execution.

## Minimal Retrieval

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
candidates = graph.retrieve_with_scores("find customer orders", top_k=8)

for item in candidates:
    print(item.tool.name, item.score, item.confidence)
```

Use `ToolGraph` directly for local tools, small services, demos, and tests.

## Artifact-Based Retrieval

Large products usually build a collection artifact once and search it many
times.

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    retrieve_graphify,
)

artifact = build_openapi_collection_artifact("openapi.json")

response = retrieve_graphify(
    artifact,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)
```

Persist the artifact in your application storage and preserve unknown fields on
rebuild.

## Target Selection

When an LLM returns a target, guard the choice with deterministic evidence:

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query=user_query,
    candidates=[row["name"] for row in response["results"]],
    tools=artifact["tools"],
    retrieval_results=response["results"],
    llm_target=llm_target,
)

target = selection["selected_target"]
```

Use `overrode_llm`, `ambiguous`, and `reason_codes` in logs or UI diagnostics.

## Plan And Execute

The plan runner calls a function you provide. Keep auth, base URLs, retries, and
downstream HTTP behavior in that function.

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

def call_tool(tool_name: str, args: dict):
    return api_executor.execute(tool_name, args, user_context=current_user)

runner = PlanRunner(call_tool)

for event in runner.run_stream(plan, trace_metadata={"request_id": request_id}):
    logger.info("plan_event", extra=asdict(event))
```

## Adapter Checklist

| Concern | Recommended Owner |
| --- | --- |
| OpenAPI parsing and graph artifact | graph-tool-call |
| Search, evidence, selector signals | graph-tool-call |
| DB table shape | application |
| Auth profile and session headers | application |
| Tool execution and mutation safety | application |
| SSE/UI forwarding | application |
| Quality Lab case storage | application |
| Trace learning suggestions | graph-tool-call schema, application storage |

## Related Pages

- [Public API](../reference/public-api.md)
- [Artifact Schemas](../reference/artifact-schemas.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Plan Synthesis](../plan/plan-synthesis.md)
