---
title: Retrieval Signals
description: Understand the ranking evidence that contributes to graph-tool-call search results.
---

# Retrieval Signals

Retrieval should be explainable. A candidate wins because of named signals, not
because a prompt happened to prefer it.

Signals are used in two places:

- ranking a compact candidate set before the LLM sees tools
- explaining why the target selector trusted or rejected a candidate

## Core Signals

| Signal | Source | Why It Matters |
| --- | --- | --- |
| `keyword_match` | tool name, operation id, summary, description | catches direct textual intent |
| `action_match` | `metadata.ai_metadata.canonical_action` | separates search/read/create/update/delete intent |
| `resource_match` | `metadata.ai_metadata.primary_resource` | keeps the business object aligned |
| `module_match` | `metadata.openapi.path_module` or operation group | scopes large enterprise APIs |
| `shape_match` | `metadata.ai_metadata.result_shape` | distinguishes list/detail/count/mutation siblings |
| `contract_match` | request and response contract fields | checks whether fields match the user's entities |
| `graph_expansion` | producer, consumer, manual, trace, or curated edges | brings nearby workflow tools into the set |
| `learning` | promoted trace-learning suggestions | applies validated local feedback as a low-weight boost |

## Evidence Output

Use `include_evidence=True` to expose signal details:

```python
from graph_tool_call.graphify import retrieve_graphify

results = retrieve_graphify(
    graph,
    "find refund-ready orders",
    top_k=5,
    include_evidence=True,
)

for row in results:
    print(row["tool_name"], row["score_breakdown"])
```

Typical output contains:

```json
{
  "tool_name": "getRefundableOrderList",
  "score_breakdown": {
    "base_retrieval": 0.42,
    "learning": 0.02,
    "action_match": 1.0,
    "resource_match": 1.0,
    "module_match": 0.0,
    "shape_match": 1.0,
    "contract_match": 1.0,
    "graph_expansion": 0.1
  },
  "candidate_evidence": {
    "semantic_match": ["action", "resource", "shape"],
    "contract_match": ["orderNo", "claimStatus"]
  }
}
```

The exact numeric scale may change across engine versions. The stable contract
is the presence of named signals and evidence fields, not a fixed absolute
score.

## How Signals Interact

| Situation | Useful Signals |
| --- | --- |
| Korean query, English operation id | keyword, aliases, Korean tokenizer, semantic metadata |
| list/detail sibling conflict | `shape_match`, response schema, operation id hints |
| tool is not directly retrieved | `graph_expansion`, producer/consumer edges |
| LLM picks wrong target | selector `rank_signals` and retrieval evidence |
| repeated successful correction | promoted `learning` suggestion |

## Tuning Principles

Prefer improving metadata and contracts before changing weights:

1. Verify the expected tool appears in Top-K.
2. Inspect `score_breakdown` and `candidate_evidence`.
3. If text is weak, improve summary or aliases.
4. If list/detail is confused, improve `result_shape`.
5. If the tool needs upstream values, inspect contract producers.
6. Only adjust weights after evidence is correct.

## Best Practice

Use `include_evidence=True` for product debug screens and regression fixtures.
Persist only the compact evidence needed to explain the ranking. Do not store
raw secrets or full API payloads.

For production logs, store:

- tool name
- rank
- score breakdown
- selected evidence keys
- token budget used
- learning suggestion id, if applied

Do not store:

- full request/response bodies
- auth headers
- cookies
- user identifiers
- raw prompt traces containing secrets

## Validation

Run retrieval-focused tests after changing scoring or metadata extraction:

```bash
poetry run pytest tests/test_graphify_metadata.py tests/test_graphify_contract_025.py -q
```

## Related Pages

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Search Tuning](./search-tuning.md)
