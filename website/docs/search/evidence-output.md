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
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph_json,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["tool_name"])
print(first["score_breakdown"])
print(first["candidate_evidence"])
```

  </TabItem>
  <TabItem value="selector" label="Selector">

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="find refund-ready orders",
    candidates=[row["tool_name"] for row in response["results"]],
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
| `query` | Normalized or original query, depending on caller path |
| `results` | Ranked candidate rows |
| `seeds` | Initial keyword or semantic matches before expansion |
| `token_budget_used` | Approximate retrieval context size |
| `graph_tool_call_version` | Engine version that produced the evidence |
| `trace_metadata` | Optional caller-provided execution/debug context |

## Candidate Row

| Field | Meaning |
| --- | --- |
| `tool_name` | Candidate tool name |
| `rank` | Candidate position in the returned list |
| `score` | Final retrieval score |
| `score_breakdown` | Named additive signals used for ranking |
| `seeds` | Matches that made the candidate visible before graph traversal |
| `expanded_from` | Candidate that caused this tool to be added |
| `edge_evidence` | Graph edge evidence used during expansion |
| `candidate_evidence` | Selector-ready action/resource/shape/contract evidence |
| `token_budget_used` | Approximate budget for this rendered candidate context |

The stable contract is the presence of named evidence fields, not a fixed
absolute score scale.

## Example Result

```json
{
  "tool_name": "getRefundableOrderList",
  "rank": 1,
  "score": 0.83,
  "score_breakdown": {
    "keyword_match": 0.31,
    "action_match": 0.16,
    "resource_match": 0.18,
    "shape_match": 0.08,
    "contract_match": 0.07,
    "graph_expansion": 0.03,
    "learning": 0.0
  },
  "candidate_evidence": {
    "semantic_match": ["search", "order", "list"],
    "contract_match": ["orderStatus", "refundStatus"],
    "result_shape": "list"
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
4. Inspect `candidate_evidence` for missing action, resource, shape, or
   contract fields.
5. Inspect `expanded_from` and `edge_evidence` when producer tools appear or
   disappear.
6. Hand the same result rows to `select_target_candidate()` before blaming the
   LLM.

## Product UI Contract

For each candidate, show compact evidence rather than raw metadata dumps.

| UI Field | Source |
| --- | --- |
| rank and tool name | `rank`, `tool_name` |
| score chips | `score_breakdown` |
| action/resource/shape badges | `candidate_evidence.semantic_match` |
| matched fields | `candidate_evidence.contract_match` |
| why it entered Top-K | `seeds`, `expanded_from` |
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
| High score but wrong target | noisy text or sibling tie | `score_breakdown`, `candidate_evidence.shape_match` |
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
      "tool_name": "getMemberDeliveryDetail",
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
