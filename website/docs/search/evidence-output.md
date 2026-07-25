---
title: Evidence Output
description: Inspect why a tool was retrieved, expanded, selected, or rejected.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Evidence Output

Evidence output is the difference between a debuggable retrieval engine and a
black-box prompt. It records the compact signals that made a tool visible,
ranked, expanded, selected, or rejected.

Use evidence output when a product needs to answer:

- why this tool was retrieved
- why a producer or neighbor tool was expanded
- why the selector accepted, rejected, or overrode an LLM target
- whether the failure came from search, selection, planning, auth, or execution
- which artifact changed between two benchmark or Quality Lab runs

## Minimal Example

<Tabs>
  <TabItem value="graphify" label="Graphify" default>

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["name"])
print(first["score_breakdown"])
print(first["semantic_evidence"])
```

  </TabItem>
  <TabItem value="selector" label="Selector">

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="find refund-ready orders",
    candidates=[row["name"] for row in response["results"]],
    tools=tools_by_name,
    retrieval_results=response["results"],
    llm_target=llm_target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
```

  </TabItem>
  <TabItem value="fixture" label="Fixture">

```json
{
  "case_id": "refund-order-search-001",
  "query": "find refund-ready orders",
  "expected_target": "getRefundableOrderList",
  "top_k": 8,
  "capture_evidence": true
}
```

  </TabItem>
</Tabs>

`include_evidence=True` is intended for product diagnostics, regression cases,
and Quality Lab-style validation. Tiny local demos can use simpler retrieval
APIs.

## Response Shape

The top-level response should be treated as an additive object. Adapters should
preserve unknown keys so newer engine versions can add evidence without breaking
older product code.

| Field | Meaning |
| --- | --- |
| `results` | Ranked candidate rows |
| `subgraph_text` | LLM-ready node/edge rendering for the selected subgraph |
| `intent` | Dominant read/write/delete/neutral intent scores |
| `stats` | Seeds, visited node/edge counts, and optional budget diagnostics |

## Candidate Row

| Field | Meaning |
| --- | --- |
| `name` | Candidate tool name |
| `score` | Final retrieval score |
| `tool` | Serialized `ToolSchema` for the candidate |
| `score_breakdown` | Named additive signals used for ranking |
| `expanded_from` | Candidate that caused this tool to be added |
| `edge_evidence` | Graph edge evidence used during expansion |
| `semantic_evidence` | Selector-ready action/resource/module/shape/contract evidence |
| `learning_evidence` | Promoted trace-learning signal, when one was applied |

The stable contract is the presence of named evidence fields, not a fixed
absolute score scale.

## Example Result

```json
{
  "name": "getRefundableOrderList",
  "score": 0.0371,
  "score_breakdown": {
    "seed": 0.0314,
    "graph": 0.0057,
    "learning": 0.0,
    "history_demoted": false,
    "action_match": 1.0,
    "resource_match": 1.0,
    "module_match": 0.0,
    "shape_match": 1.0,
    "contract_match": 1.0,
    "graph_expansion": 0.0
  },
  "semantic_evidence": {
    "canonical_action": "search",
    "primary_resource": "order",
    "result_shape": "list",
    "path_module": "/orders",
    "action_match": true,
    "resource_match": true,
    "module_match": false,
    "shape_match": true,
    "contract_match": true,
    "matched_terms": ["order", "refund"]
  },
  "edge_evidence": []
}
```

Read this as a ranked explanation, not as a promise that every future version
will use the same numeric weights.

## Diagnostic Workflow

Use the evidence object in this order:

1. Confirm the expected target is present in `results`.
2. Check whether its rank is acceptable for the caller's Top-K.
3. Compare `score_breakdown` against the wrong higher-ranked tools.
4. Inspect `semantic_evidence` for missing action, resource, shape, or
   contract fields.
5. Inspect `expanded_from` and `edge_evidence` when producer tools appear or
   disappear.
6. Hand the same result rows to `select_target_candidate()` before blaming the
   LLM.

## Product UI Contract

For each candidate, show compact evidence rather than raw metadata dumps.

| UI Field | Source |
| --- | --- |
| rank and tool name | list position, `name` |
| score chips | `score_breakdown` |
| action/resource/shape badges | `semantic_evidence.action_match`, `resource_match`, `shape_match` |
| matched terms | `semantic_evidence.matched_terms` |
| why it entered Top-K | `stats.seeds`, `expanded_from` |
| graph reason | `edge_evidence.kind`, `edge_evidence.evidence` |

For a selected target, add:

| UI Field | Source |
| --- | --- |
| LLM target | `target_selector.llm_target` |
| final selected target | `target_selector.selected_target` |
| override state | `target_selector.overrode_llm` |
| uncertainty | `target_selector.ambiguous`, `reason_codes` |
| policy | `target_selector.policy` |

This is enough for operators to distinguish search failure, selector ambiguity,
missing input, auth readiness, and downstream API failure.

## Persistence Policy

Persist compact, scrubbed evidence that helps reproduce the decision. Do not
store raw request bodies, response bodies, tokens, cookies, or user identifiers.

Store:

- query fingerprint or test case id
- candidate list and rank
- score breakdown
- selector reason codes
- graph/tool version
- scrubbed trace metadata
- learning suggestion id, if applied

Do not store:

- full API response body
- authorization headers
- cookies
- raw user ids
- phone, email, address, or account-like payload values
- raw prompt traces containing secrets

## Failure Modes

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| High score but wrong target | noisy text or sibling tie | `score_breakdown`, `semantic_evidence.shape_match` |
| Correct target missing | weak metadata or missing aliases | indexed action/resource/module fields |
| Producer missing from catalog | contract extraction gap | `api_contract.consumes`, `api_contract.produces` |
| Too many producers | broad data-flow edge or context field explosion | `edge_evidence`, contract field kind |
| Selector refused to override | insufficient margin | `target_selector.rank_signals` |
| Evidence is empty | caller used a simple retrieval path | switch to `retrieve_graphify(..., include_evidence=True)` |
| Evidence changed after rebuild | artifact or semantic metadata changed | compare `graph_tool_call_version`, `semantic_summary` |

## Regression Fixture

Store evidence for failing and fixed runs so reviews can compare artifacts
instead of relying on memory.

```json
{
  "case_id": "member-delivery-detail-001",
  "query": "show member delivery detail",
  "expected_target": "getMemberDeliveryDetail",
  "actual_top_3": [
    {
      "name": "getMemberDeliveryDetail",
      "rank": 1,
      "score_breakdown": {
        "resource_match": 0.18,
        "shape_match": 0.08,
        "contract_match": 0.07
      }
    }
  ],
  "target_selector": {
    "selected_target": "getMemberDeliveryDetail",
    "reason_codes": ["selected_by_strong_evidence"]
  }
}
```

## Validation

Evidence output should be captured in regression fixtures when tuning ranking.
For a failing query, keep the evidence from both the old and new run.

Useful checks:

```bash
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Target Selection](./target-selection.md)
- [Trace Learning](../concepts/trace-learning.md)
