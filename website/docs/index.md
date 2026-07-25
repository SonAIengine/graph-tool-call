---
title: Documentation
description: Start building searchable tool graphs for large LLM tool catalogs.
---

# graph-tool-call documentation

`graph-tool-call` is a graph-structured tool retrieval engine for LLM agents.
It turns OpenAPI specs, MCP tools, and Python functions into searchable tool
graphs, then returns compact candidates, execution contracts, target-selection
evidence, and quality diagnostics.

Use this manual when your agent has more tools than can safely fit in model
context, or when "the right tool" depends on request fields, response fields,
workflow order, auth readiness, and past run evidence.

## Choose Your Path

| Goal | Start Here | You Should End With |
| --- | --- | --- |
| Try the library locally | [Quickstart](getting-started/quickstart.md) | a first OpenAPI search, graph build, and readiness check |
| Understand the architecture | [Mental Model](getting-started/mental-model.md) | the ingest -> contract -> retrieve -> select -> plan -> learn model |
| Build from Swagger/OpenAPI | [OpenAPI Ingestion](build/openapi-ingestion.md) | a collection artifact with contracts and semantic metadata |
| Search a large catalog | [Tool Graph Search](search/tool-graph-search.mdx) | ranked candidates with score/evidence output |
| Guard an LLM target choice | [Target Selection](search/target-selection.md) | deterministic selector diagnostics around `llm_target` |
| Execute multi-tool workflows | [Plan Synthesis](plan/plan-synthesis.md) | a plan, user input slots, runner events, and failure reasons |
| Validate quality | [Quality Lab](validation/quality-lab.md) | repeatable search, plan, execute, and benchmark gates |
| Connect an application | [XGEN Integration](guides/xgen-integration.md) | a product adapter that owns DB, auth, UI, SSE, and execution |

## Minimal Retrieval

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
results = graph.retrieve_with_scores("find pets by status", top_k=3)

for row in results:
    print(row.tool.name, row.score)
```

For debugging, request the evidence object rather than sending every tool schema
to the LLM:

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph,
    "find pets by status",
    top_k=3,
    include_evidence=True,
)

first = response["results"][0]
print(first["score_breakdown"])
```

## Core Workflows

| Workflow | Manual | Key Artifacts |
| --- | --- | --- |
| Build catalog | [Build Tool Catalogs](build/openapi-ingestion.md) | `ToolSchema`, `api_contract`, `semantic_summary`, readiness report |
| Search and select | [Search And Selection](search/tool-graph-search.mdx) | retrieval rows, score breakdown, `target_selector` |
| Plan and execute | [Plan And Execute](plan/plan-synthesis.md) | `Plan`, `PlanStep`, `user_input_slots`, runner events |
| Learn from traces | [Learning Loop](concepts/trace-learning.md) | scrubbed attempts, suggestions, shadow/promotion state |
| Validate claims | [Validation](validation/benchmarks.md) | benchmark artifacts, Quality Lab results, release gates |
| Integrate clients | [Integrations](guides/xgen-integration.md) | XGEN adapter, MCP gateway, LangChain tools, middleware patches |
| Look up contracts | [Reference](reference/public-api.md) | public imports, CLI, event schemas, report schemas |

## What The Engine Owns

The library is product-neutral. It should own deterministic graph/search/plan
logic and artifacts that can be inspected or tested.

| Engine Responsibility | Product Adapter Responsibility |
| --- | --- |
| OpenAPI/MCP/Python ingestion | source storage and tenant policy |
| request/response contract extraction | user/session auth resolution |
| retrieval and score evidence | model/provider routing |
| target selector diagnostics | UI decisions and user confirmation |
| plan synthesis and runner event schema | actual HTTP execution and audit logging |
| trace-learning suggestions | approval, rejection, and rollout policy |

## Quality Expectations

Good tool retrieval work should be reproducible. Before publishing a quality
claim or wiring a large collection into production, make sure you have:

- a committed fixture or named live collection
- deterministic search/selector metrics
- a plan/execute gate if execution is claimed
- model/provider information for any LLM-based result
- raw result artifacts or Quality Lab records
- an explicit note when a benchmark is synthetic, shadow-mode, or read-only

## Manual Map

| Section | Use It For |
| --- | --- |
| [Getting Started](getting-started/quickstart.md) | installation, quickstart, mental model |
| [Build Tool Catalogs](build/openapi-ingestion.md) | OpenAPI, MCP, Python ingestion, semantic build, IO contracts, readiness |
| [Search And Selection](search/tool-graph-search.mdx) | retrieval, evidence, candidate expansion, target selector, Korean search |
| [Plan And Execute](plan/plan-synthesis.md) | plan synthesis, user slots, runner events, failure taxonomy |
| [Learning Loop](concepts/trace-learning.md) | scrubbed traces, suggestions, shadow mode, promotion policy |
| [Validation](validation/benchmarks.md) | benchmark gates, Quality Lab, release gates |
| [Integrations](guides/xgen-integration.md) | XGEN, MCP, LangChain, middleware, direct API adapters |
| [Reference](reference/public-api.md) | public imports, CLI, events, reports, artifacts, compatibility |
