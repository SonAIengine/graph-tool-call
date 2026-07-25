---
title: Search Tuning
description: Improve retrieval quality with aliases, semantic metadata, contracts, learning evidence, and repeatable validation gates.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Search Tuning

Search tuning is the process of improving tool retrieval without turning the
LLM prompt into the only source of truth. Tune the catalog evidence first, then
the ranking policy, and only then the prompt.

The goal is not to make one manual query look better. The goal is to make a
named query suite improve in a way that can be reproduced, reviewed, and
rolled back.

## Tuning Loop

```text
choose query suite
  -> capture baseline evidence
  -> classify misses
  -> improve evidence
     metadata/contracts/aliases
  -> rerun the same suite
  -> compare metrics
     and evidence
  -> promote repeatable
     improvements
```

Use the same fixture, source artifact, and Top-K value before and after the
change. Otherwise, the result is not a meaningful comparison.

## Start With A Query Suite

Create a small suite that represents real work. Each case should have a query,
the expected target, and the stage you want to validate.

<Tabs>
  <TabItem value="search" label="Search" default>

```json
{
  "id": "refund_list",
  "query": "find refund-ready orders",
  "expected_target": "searchOrders",
  "mode": "search",
  "top_k": 8
}
```

  </TabItem>
  <TabItem value="plan" label="Plan">

```json
{
  "id": "order_detail",
  "query": "get order detail for order 1001",
  "expected_target": "getOrderDetail",
  "mode": "plan",
  "provided_entities": {"orderId": "1001"}
}
```

  </TabItem>
  <TabItem value="execute" label="Execute">

```json
{
  "id": "readonly_detail",
  "query": "get order detail for order 1001",
  "expected_target": "getOrderDetail",
  "mode": "execute",
  "mutation_safety": "read_only",
  "assertions": [{"path": "status", "exists": true}]
}
```

  </TabItem>
</Tabs>

Keep the suite small during development. Broaden it before release or public
quality claims.

## Capture Evidence

Use `include_evidence=True` whenever you tune search. The evidence object is the
debuggable contract between retrieval, target selection, planning, and product
UI.

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
baseline = retrieve_graphify(
    graph,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

for row in baseline["results"]:
    print(row["name"])
    print(row["score_breakdown"])
    print(row.get("semantic_evidence", {}))
```

Capture:

- ranked candidate names
- expected target rank
- score breakdown
- semantic and contract evidence
- graph expansion source
- token budget used
- selector decision, if target selection is part of the case

Do not store raw auth headers, cookies, full request bodies, full response
bodies, user identifiers, or secrets.

## Read The Signals

Start with evidence quality. Weight changes should be the last step.

| Signal | Inspect When | Likely Fix |
| --- | --- | --- |
| `seed` | expected tool is outside Top-K | names, summaries, aliases |
| `action_match` | search/read/create/update/delete intent is wrong | `canonical_action` derivation |
| `resource_match` | right action but wrong object | `primary_resource` or resource aliases |
| `module_match` | large catalog returns another domain | `path_module`, operation group, module aliases |
| `shape_match` | list/detail/count/mutation sibling is wrong | `result_shape` derivation |
| `contract_match` | query entities are ignored | request/response contract extraction |
| `graph_expansion` | producer or next-step tool is missing | data-flow edges and producer expansion |
| `learning` | repeated successful corrections are not reused | shadow/promotion state |

If a signal is empty, fix the source evidence. If a signal exists but is
underweighted across many cases, then consider tuning weights.

## Miss Taxonomy

Classify every failing case before changing code.

| Category | Meaning | First Place To Look |
| --- | --- | --- |
| `not_retrieved` | expected target is outside Top-K | indexed text and semantic metadata |
| `low_rank` | expected target appears but is below weaker siblings | score breakdown and shape/resource evidence |
| `wrong_shape` | list/detail/count/mutation is confused | `result_shape`, response schema, operation id |
| `wrong_resource` | action is right but business object is wrong | `primary_resource`, path module, aliases |
| `module_leak` | another domain wins in a large catalog | `path_module`, source label, module aliases |
| `producer_missing` | target found, plan cannot fill required fields | `api_contract.produces` and data-flow edges |
| `selector_mismatch` | correct tool is in Top-K but final target is wrong | `target_selector.rank_signals` |
| `auth_or_execute` | search/plan passed but API call failed | auth readiness, runner events, HTTP status |

Do not mix categories. A search miss and an execution auth failure need
different fixes.

## Tuning Actions

Apply the smallest product-neutral fix that improves the evidence.

| Action | Scope | Notes |
| --- | --- | --- |
| add generic aliases | adapter options | Good when users use business terms absent from OpenAPI |
| improve semantic derivation | engine | Good when many operations share the same naming pattern |
| repair response schemas | source or adapter repair | Required for producer expansion and result shape |
| repair request schemas | source or adapter repair | Required for plan synthesis and missing field diagnostics |
| add manual edge | artifact metadata | Use for known workflow relations that the source cannot express |
| promote learning suggestion | collection-local | Use only after repeated validated success |
| adjust ranking weight | engine policy | Use only after evidence exists and many cases support the change |

Avoid one-off operation-name hacks in the engine. If the rule mentions a single
customer, endpoint, or private field name, it belongs in adapter options or
manual metadata.

## Alias Strategy

Aliases are useful when users and OpenAPI authors use different words.

```python
artifact = build_openapi_collection_artifact(
    "openapi.json",
    semantic_options={
        "resource_aliases": {
            "refund": "claim",
            "buyer": "customer",
            "delivery": "shipment",
        },
        "action_aliases": {
            "lookup": "read",
            "find": "search",
        },
    },
)
```

Keep aliases generic. Product adapters can pass customer-specific aliases at
build time; the library should remain reusable.

## Selector Tuning

When the expected target is already in Top-K, inspect target selection instead
of widening retrieval.

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query=case["query"],
    candidates=[
        row["name"]
        for row in retrieval["results"]
    ],
    tools=artifact["tools"],
    retrieval_results=retrieval["results"],
    llm_target=llm_target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
print(selection["rank_signals"])
```

A selector override is healthy only when strong evidence and enough margin
exist. Weak evidence should produce `ambiguous_target`, not a silent correction.

## Learning Evidence

Trace learning should be conservative:

1. Store scrubbed attempts.
2. Create suggestions in shadow mode.
3. Compare baseline rank with learning-applied shadow rank.
4. Promote only repeated successful target or plan-path evidence.
5. Keep learning boosts low-weight and visible in `rank_signals`.

Never treat one successful run as permanent ranking truth.

## Acceptance Gates

A tuning change should report at least:

| Metric | Why It Matters |
| --- | --- |
| query count | prevents overclaiming from one example |
| Top-1 hit rate | direct ranking quality |
| Top-3 or Top-8 hit rate | recall for LLM/selector handoff |
| average candidate count | context pressure |
| max candidate count | worst-case prompt size |
| selector override count | guardrail activity |
| selector ambiguity count | unresolved sibling confusion |
| plan hit rate | whether search results are usable by planning |
| `unsatisfied_field` count | contract quality |
| uncaught error count | adapter/runtime stability |

For public claims, record model/provider information whenever an LLM is part of
the result.

## Anti-Patterns

Avoid:

- hard-coding product-specific operation names in the engine
- boosting raw descriptions until noisy OpenAPI text dominates results
- changing global weights to fix one query
- declaring improvement from a manual demo query
- widening Top-K until the correct tool appears but the LLM sees too much
- storing secrets or raw API payloads as search evidence
- promoting learning suggestions without repeated validation

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Validation Benchmarks](../validation/benchmarks.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../learning/shadow-promotion.md)
