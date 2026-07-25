---
title: Mental Model
description: Understand how graph-tool-call prepares a compact, evidence-backed tool surface before an LLM acts.
---

# Mental Model

`graph-tool-call` is a retrieval and planning engine for large tool catalogs.

It does not replace the LLM. It prepares the tool surface so the LLM sees a
smaller, better ranked, and better explained set of choices.

## The Core Problem

Large tool catalogs fail for predictable reasons:

- the LLM receives too many loosely described tools
- similar operations have weak action and resource metadata
- request and response schemas are not converted into usable contracts
- the correct tool is in Top-K but the final target selection drifts
- missing fields are discovered only after execution starts
- auth, request, API, and cleanup failures are mixed together
- successful retries are not fed back into future search

graph-tool-call turns the catalog into inspectable evidence before the LLM acts.

## Pipeline

```text
source
  -> ingest
  -> contract extraction
  -> semantic build
  -> graph build
  -> retrieval
  -> target selection
  -> plan synthesis
  -> runner events
  -> trace learning
```

Each stage creates an artifact that can be stored, inspected, tested, and passed
to a product adapter.

## Stage Overview

| Stage | What Happens | Main Artifact |
| --- | --- | --- |
| ingest | OpenAPI, MCP, and Python sources become tools | `ToolSchema` |
| contract extraction | request/response/auth/context fields are extracted | `metadata.api_contract` |
| semantic build | action, resource, module, and result shape are inferred | `metadata.ai_metadata` |
| graph build | structural, contract, manual, and trace edges are merged | graph artifact |
| retrieval | a compact candidate set is ranked for the query | retrieval results |
| target selection | LLM target is guarded by deterministic evidence | `target_selector` |
| plan synthesis | producers, bindings, and user input slots are ordered | `Plan` |
| run | adapter executes tools and streams structured events | runner events |
| learn | scrubbed traces become suggestions after validation | learning state |

## Artifact Flow

| Artifact | Why It Exists | Where It Usually Lives |
| --- | --- | --- |
| `ToolSchema` | stable tool description and parameters | engine memory or adapter storage |
| `metadata.openapi` | original OpenAPI operation evidence | collection artifact |
| `metadata.api_contract` | consumes, produces, links, auth fields | collection artifact |
| `metadata.ai_metadata` | action/resource/module/search summary | collection artifact |
| `readiness_report` | build-time issue codes and readiness score | collection artifact and UI |
| retrieval evidence | score breakdown and matched signals | request trace or Quality Lab |
| `target_selector` | final target decision and override reason | plan metadata |
| `Plan` | executable ordered steps and bindings | request runtime |
| runner events | streamable execution state and failures | SSE/log/Quality Lab |
| learning suggestions | safe feedback from repeated execution traces | collection-scoped learning block |

The same artifact should be useful to a human, a test, and an adapter. If an
important decision exists only inside a prompt, it is hard to debug.

## Engine vs Adapter

graph-tool-call owns product-neutral logic.

| Engine Owns | Adapter Owns |
| --- | --- |
| schema normalization | database rows |
| semantic metadata | user sessions |
| IO contracts | auth profiles |
| graph edges | HTTP execution |
| retrieval evidence | cookies and runtime headers |
| target selection | SSE transport |
| plan synthesis diagnostics | UI workflows |
| learning suggestions | collection persistence and promotion policy |

This boundary keeps the library reusable. XGEN can pass auth profiles and store
collection artifacts without putting XGEN-specific DB, cookie, or UI logic into
the engine.

## Why A Graph

A list of tools hides relationships. A graph makes them explicit:

- tool A produces a field that tool B consumes
- several operations share the same primary resource
- a search operation can produce identifiers for a detail operation
- a manually curated edge is stronger than a weak name-based edge
- a repeated successful run can become trace evidence

This matters for planning. The engine can synthesize producer steps because the
catalog contains field and edge evidence, not just descriptions.

## What The LLM Still Does

The LLM still matters. It can:

- interpret natural-language intent
- choose among a compact, ranked candidate set
- fill natural-language gaps
- produce a user-facing final response
- reason over evidence that the engine provides

The engine keeps the LLM away from avoidable catalog noise. The first
optimization target is better evidence, not model fine-tuning.

## Search To Plan Example

```python
from graph_tool_call import ToolGraph
from graph_tool_call.plan import PathSynthesizer

graph = ToolGraph.from_url(openapi_url)

results = graph.retrieve_with_scores(
    "show refund-ready orders",
    top_k=8,
)

target = results[0].tool.name
graph_payload = {
    "graph": graph.graph.to_dict(),
    "tools": {name: tool.to_dict() for name, tool in graph.tools.items()},
}

plan = PathSynthesizer(graph_payload).synthesize(
    target=target,
    goal="show refund-ready orders",
    entities={"siteNo": "1001"},
)
```

The retrieval result explains why a tool was ranked. The plan explains which
fields are already satisfied, which producers are needed, and which values must
come from user input or context defaults.

## Failure Handling

When a run fails, classify the stage before changing prompts.

| Symptom | Likely Stage | First Document To Read |
| --- | --- | --- |
| expected tool not in Top-K | retrieval | [Retrieval Signals](../search/retrieval-signals.md) |
| expected tool in Top-K but final target is wrong | target selection | [Target Selection](../search/target-selection.md) |
| plan asks for an obvious field | plan synthesis | [User Input Slots](../plan/user-input-slots.md) |
| execute stops before API call | auth preflight | [Auth Readiness](../build/auth-readiness.md) |
| API returns 400, 401, or 500 | execute | [Failure Taxonomy](../plan/failure-taxonomy.md) |
| retry succeeds but future search does not improve | learning | [Trace Learning Loop](../concepts/trace-learning.md) |

## Quality Loop

Quality should be measured as a loop:

1. build the catalog
2. inspect readiness and graph evidence
3. run search cases
4. run target-selection cases
5. run plan and execute cases when auth is available
6. store scrubbed traces
7. compare learning in shadow mode
8. promote only validated suggestions

This gives you repeatable evidence instead of relying on a single demo.

## Next Steps

- Start with [Quickstart](./quickstart.md) if you want a minimal retrieval flow.
- Read [OpenAPI Ingestion](../build/openapi-ingestion.md) when building a catalog.
- Read [Target Selection](../search/target-selection.md) when LLM choices drift.
- Read [Plan Synthesis](../plan/plan-synthesis.md) when chaining tools.
- Read [Quality Lab](../validation/quality-lab.md) before making quality claims.
