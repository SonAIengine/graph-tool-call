---
title: Retrieval Signals
description: Understand the ranking evidence that contributes to graph-tool-call search results.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Retrieval Signals

Retrieval should be explainable. A candidate wins because of named signals, not
because a prompt happened to prefer it.

Signals are used in two places:

- ranking a compact candidate set before the LLM sees tools
- explaining why the target selector trusted or rejected a candidate

## Signal Pipeline

The retrieval path is intentionally split into inspectable stages. Adapters can
store each stage as compact evidence without saving prompts, secrets, or full API
payloads.

| Stage | Input | Output | Debug Object |
| --- | --- | --- | --- |
| Query normalization | user query | tokens, aliases, inferred shape | `seeds` |
| Candidate retrieval | indexed tool text and metadata | ranked tools | `score_breakdown` |
| Contract matching | request/response fields | consumes/produces matches | `candidate_evidence.contract_match` |
| Graph expansion | deterministic and promoted edges | producer/neighbor tools | `expanded_from`, `edge_evidence` |
| Selector handoff | Top-K candidates | selector-ready ranking rows | `candidate_evidence` |

This makes retrieval closer to a query engine than to a prompt heuristic: each
candidate can explain which artifact made it visible.

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

<Tabs>
  <TabItem value="graphify" label="Graphify" default>

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph_json,
    "find refund-ready orders",
    top_k=5,
    include_evidence=True,
)

for row in response["results"]:
    print(row["tool_name"], row["score_breakdown"])
```

  </TabItem>
  <TabItem value="toolgraph" label="ToolGraph">

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
rows = graph.retrieve_with_scores(
    "find refund-ready orders",
    top_k=5,
)

for row in rows:
    print(row.tool.name, row.score)
```

  </TabItem>
  <TabItem value="cli" label="CLI">

```bash
graph-tool-call search "find refund-ready orders" \
  --source openapi.json \
  --top-k 5 \
  --scores
```

  </TabItem>
</Tabs>

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

## Reading A Result Row

Start with the result row before changing weights. Most search failures are
caused by missing metadata or missing contracts, not by one bad score constant.

| Field | What To Ask |
| --- | --- |
| `tool_name` | Is the expected tool present in Top-K? |
| `rank` | Is the tool too low, or absent entirely? |
| `score_breakdown.keyword_match` | Did names, summaries, and operation ids match the query? |
| `score_breakdown.action_match` | Did the query verb match `canonical_action`? |
| `score_breakdown.resource_match` | Did the business object match `primary_resource`? |
| `score_breakdown.shape_match` | Did list/detail/count/mutation intent match `result_shape`? |
| `candidate_evidence.contract_match` | Did request/response fields fit the query? |
| `edge_evidence` | Was the candidate added because of a graph relation? |
| `token_budget_used` | Is retrieval returning too much context to the LLM? |

If the expected tool is absent, fix ingest, semantic metadata, aliases, or
contract extraction. If it is present but the LLM chooses a sibling, inspect
[Target Selection](./target-selection.md).

## How Signals Interact

| Situation | Useful Signals |
| --- | --- |
| Korean query, English operation id | keyword, aliases, Korean tokenizer, semantic metadata |
| list/detail sibling conflict | `shape_match`, response schema, operation id hints |
| tool is not directly retrieved | `graph_expansion`, producer/consumer edges |
| LLM picks wrong target | selector `rank_signals` and retrieval evidence |
| repeated successful correction | promoted `learning` suggestion |

## Example: List vs Detail Siblings

Large OpenAPI catalogs often contain sibling operations whose names differ by
one word. The selector can only help if retrieval preserves evidence for both
candidates.

```python
response = retrieve_graphify(
    graph_json,
    "show member delivery detail",
    top_k=8,
    include_evidence=True,
)

for row in response["results"]:
    print(
        row["tool_name"],
        row["score_breakdown"].get("shape_match"),
        row["candidate_evidence"].get("semantic_match"),
    )
```

Expected behavior:

| Candidate | Good Evidence |
| --- | --- |
| `getMemberDeliveryDetail` | `read`, `member_delivery`, `single`, response fields |
| `getMemberDeliveryList` | `read`, `member_delivery`, `list`, weaker shape match |
| `getMemberInfo` | `read`, `member`, partial resource match |

If all candidates look identical, improve `result_shape`, `primary_resource`,
or response contract coverage before adjusting search weights.

## Tuning Principles

Prefer improving metadata and contracts before changing weights:

1. Verify the expected tool appears in Top-K.
2. Inspect `score_breakdown` and `candidate_evidence`.
3. If text is weak, improve summary or aliases.
4. If list/detail is confused, improve `result_shape`.
5. If the tool needs upstream values, inspect contract producers.
6. Only adjust weights after evidence is correct.

## Signal Quality Checklist

Use this checklist when a collection is rebuilt or a new source is added.

| Check | Healthy Sign |
| --- | --- |
| action coverage | most tools have known `canonical_action` |
| resource coverage | tools are assigned to stable `primary_resource` values |
| module coverage | large APIs split into path/module groups |
| contract coverage | request and response fields appear in `api_contract` |
| evidence density | Top-K rows have at least one semantic or contract signal |
| expansion restraint | graph expansion adds producers without flooding candidates |
| learning restraint | only promoted suggestions affect ranking |

These checks should be visible in product diagnostics and release gates. They
are also the fastest way to find whether the issue is search, selector, plan, or
adapter execution.

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

## Adapter Display Contract

When exposing retrieval diagnostics in a product UI, show a compact comparison
instead of dumping raw metadata:

| UI Field | Source |
| --- | --- |
| rank and tool name | result row |
| action/resource/shape badges | `candidate_evidence.semantic_match` |
| matched fields | `candidate_evidence.contract_match` |
| why it entered Top-K | `seeds` and `expanded_from` |
| selection outcome | `target_selector.selected_target` |
| uncertainty | `ambiguous`, `reason_codes` |

This keeps debugging usable even when a collection has hundreds or thousands of
tools.

## Validation

Run retrieval-focused tests after changing scoring or metadata extraction:

```bash
poetry run pytest tests/test_graphify_metadata.py tests/test_graphify_contract_025.py -q
```

## Related Pages

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Search Tuning](./search-tuning.md)
