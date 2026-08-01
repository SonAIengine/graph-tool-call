---
title: API Cheat Sheet
description: Pick the right public API or CLI command for each graph-tool-call workflow.
---

# API Cheat Sheet

Use this page when you know the job you need to do, but not which public API
belongs to that job. It is intentionally short: each row points to the stable
entry point, the output you should expect, and the manual page that explains the
details.

## Decision Matrix

| Job | Public API Or CLI | Output | Read Next |
| --- | --- | --- | --- |
| Try retrieval against one OpenAPI source | `ToolGraph.from_url(...).retrieve_with_scores(...)` or `graph-tool-call search` | ranked `RetrievalResult` rows | [Quickstart](../getting-started/quickstart.md) |
| Build a persisted collection artifact | `build_openapi_collection_artifact(...)` or `graph-tool-call build-openapi-collection` | `collection.json` with tools, graph, readiness, semantics | [Collection Artifacts](../build/collection-artifacts.md) |
| Inspect an OpenAPI source before build | `analyze_openapi_collection(...)` or `graph-tool-call inspect-openapi` | `OpenAPICollectionReport` | [Readiness Diagnostics](../build/readiness-diagnostics.md) |
| Extract operation contracts | `extract_openapi_contract_index(...)` | operation contract rows with schemas and security | [IO Contracts](../build/io-contracts.md) |
| Search a stored artifact with evidence | `ToolGraph.load(...)` plus `retrieve_graphify(...)` | response object with `results`, `subgraph_text`, `intent`, `stats` | [Tool Graph Search](../search/tool-graph-search.mdx) |
| Select the final target | `select_target_candidate(...)` | `selected_target`, confidence, reason codes, candidate evidence | [Target Selection](../search/target-selection.md) |
| Complete target dependencies | `complete_target_dependencies(...)` and `assemble_tool_bundle(...)` | evidence-gated closure and token-accounted role bundle | [Candidate Expansion](../search/candidate-expansion.md) |
| Build a deterministic plan | `PathSynthesizer(...).synthesize(...)` | `Plan` with steps and synthesis metadata | [Plan Synthesis](../plan/plan-synthesis.md) |
| Stream execution events | `PlanRunner(...).run_stream(...)` | typed runner events convertible with `asdict(event)` | [Runner Events](../plan/runner-events.md) |
| Store trace learning evidence | `build_trace_learning_record(...)` and `derive_learning_suggestions(...)` | scrubbed attempt record and suggestions | [Trace Learning](../concepts/trace-learning.md) |
| Expose a filtered MCP surface | `graph-tool-call serve` or `graph-tool-call proxy` | MCP server/proxy endpoint | [MCP Server](../integrations/mcp-server.md) |

## Minimal OpenAPI Build

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"tenantId", "siteNo"},
    paging_field_names={"page", "size"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

Use the collection artifact when a service or UI needs to store diagnostics,
quality results, learning suggestions, or manual operator metadata.

## Minimal Evidence Retrieval

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    "find refund-ready order list",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["name"])
print(first["score_breakdown"])
print(first["semantic_evidence"])
print(response["stats"])
```

Treat `response["results"]` as the selector-ready candidate set. Treat
`response["subgraph_text"]` as the compact context block for a downstream LLM.

## Minimal Target Guard

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="find refund-ready order list",
    candidates=[row["name"] for row in response["results"]],
    tools=graph.tools,
    retrieval_results=response["results"],
    llm_target="getOrderDetail",
)

print(selection["selected_target"])
print(selection["overrode_llm"])
print(selection["reason_codes"])
```

The default selector policy is conservative. It records ambiguity instead of
silently overriding weak LLM choices.

## Minimal Plan

```python
from graph_tool_call.plan import PathSynthesizer, PlanSynthesisError

graph_payload = {
    "graph": graph.graph.to_dict(),
    "tools": {name: tool.to_dict() for name, tool in graph.tools.items()},
}

try:
    plan = PathSynthesizer(
        graph_payload,
        context_defaults={"siteNo": "1001"},
    ).synthesize(
        target=selection["selected_target"],
        goal="find refund-ready order list",
        entities={"keyword": "refund-ready"},
    )
except PlanSynthesisError as exc:
    print(exc.to_dict())
else:
    print(plan.id)
    print([step.tool for step in plan.steps])
    print(plan.metadata["synthesis"])
```

Store `exc.to_dict()` rather than parsing exception strings.

## Adapter Boundary

Keep graph-tool-call product-neutral:

| Keep In graph-tool-call | Keep In Your Adapter |
| --- | --- |
| schema normalization and contract extraction | source storage and tenant policy |
| retrieval, evidence, and target selection | LLM provider/model routing |
| plan schemas and runner event contracts | auth headers, cookies, user ids, SSE, UI |
| scrubbed trace-learning helpers | approval workflow and rollout policy |

## Quality Checklist

Before wiring a large catalog into an agent, make sure you can answer:

- Did `inspect-openapi` return `ready` or a known `warning`?
- Does retrieval return the expected target within your Top-K gate?
- Does `score_breakdown` show action/resource/shape/contract evidence?
- Did `select_target_candidate()` select or explicitly mark ambiguity?
- Does `PathSynthesizer` produce a plan or a structured failure reason?
- Is execute blocked by auth readiness before any unsafe API call?

## Related Pages

- [Public API](./public-api.md)
- [CLI](./cli.md)
- [Artifact Schemas](./artifact-schemas.md)
- [Quality Gates](../guides/quality-gates.md)
