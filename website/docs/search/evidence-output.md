---
title: Evidence Output
description: Inspect why a tool was retrieved, expanded, or selected.
---

# Evidence Output

Evidence output is the main difference between a debuggable retrieval engine and
a black-box prompt.

Use it when a product needs to answer:

- why this tool was retrieved
- why a producer tool was expanded
- why the selector accepted or overrode an LLM target
- whether the failure came from search, selection, planning, auth, or execution

## Minimal Example

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["tool_name"])
print(first["score_breakdown"])
print(first["candidate_evidence"])
```

`include_evidence=True` is intended for product diagnostics, regression cases,
and Quality Lab-style validation. It is not necessary for a tiny local demo.

## Result Fields

| Field | Meaning |
| --- | --- |
| `tool_name` | Candidate tool name |
| `score` | Final retrieval score |
| `score_breakdown` | Named additive signals used for ranking |
| `seeds` | Initial keyword/semantic matches before graph traversal |
| `expanded_from` | Candidate that caused this tool to be added |
| `edge_evidence` | Graph edge evidence used during expansion |
| `candidate_evidence` | Selector-ready action/resource/shape/contract evidence |
| `token_budget_used` | Approximate context budget used by rendered subgraph |

The exact set is additive. Product code should preserve unknown fields so newer
engine versions can expose more evidence without breaking older adapters.

## Product UI Checklist

For each candidate, show:

- rank
- score
- score breakdown
- matched action/resource/module
- contract fields that matched
- graph expansion source
- selector reason codes

For a selected target, also show:

- LLM target
- final selected target
- whether selector overrode the LLM
- ambiguity flag
- selector policy
- reason codes

## Persistence Policy

Persist compact, scrubbed evidence that helps reproduce the decision. Avoid raw
request bodies, response bodies, tokens, cookies, and user identifiers.

Store:

- query fingerprint or test case id
- candidate list and rank
- score breakdown
- selector reason codes
- graph/tool version
- scrubbed trace metadata

Do not store:

- full API response body
- authorization headers
- cookies
- raw user ids
- personal data from request/response payloads

## Failure Modes

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| High score but wrong target | noisy text or sibling tie | `score_breakdown`, `candidate_evidence.shape_match` |
| Correct target missing | weak metadata or missing aliases | indexed action/resource/module fields |
| Producer missing from catalog | contract extraction gap | `api_contract.consumes`, `api_contract.produces` |
| Selector refused to override | insufficient margin | `target_selector.rank_signals` |
| Evidence is empty | caller used `ToolGraph.retrieve()` instead of graphify evidence path | switch to `retrieve_graphify(..., include_evidence=True)` |

## Validation

Evidence output should be captured in regression fixtures when tuning ranking.
For a failing query, keep the evidence from both the old and new run so changes
can be reviewed without guessing.

Useful checks:

```bash
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Target Selection](./target-selection.md)
- [Trace Learning](../concepts/trace-learning.md)
