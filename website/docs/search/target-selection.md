---
title: Target Selection
description: Choose the final tool from retrieved candidates with deterministic evidence and LLM guardrails.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Target Selection

Target selection is the decision layer between retrieval and plan synthesis. It
receives a small candidate set, compares the candidates with stable semantic and
contract evidence, and returns the final tool that should be planned.

The selector does not replace the LLM. It gives the LLM a safer operating
boundary. When deterministic evidence is strong and the LLM selected a weaker
sibling, the selector can override. When evidence is close, it keeps the LLM
target and records ambiguity.

Use this page when you need to explain why a specific tool was selected, why an
LLM target was overridden, or why a Quality Lab case passed search but failed
planning.

## Where It Runs

The selector sits after graph retrieval and before `PathSynthesizer`.

| Stage | Input | Output | Failure Signal |
| --- | --- | --- | --- |
| Retrieve | query, graph artifact | ranked candidates | expected tool absent from Top-K |
| LLM intent | query, compact catalog | optional `llm_target` | LLM picks a sibling or external tool |
| Select | query, candidates, evidence | `target_selector` block | `ambiguous_target`, `no_candidates` |
| Plan | selected target, entities | executable `Plan` | `unsatisfied_field`, `enum_required` |
| Execute | plan, adapter auth | runner events | auth/API/request failure |

If the correct tool is absent from retrieval Top-K, fix search first. Target
selection is designed to choose among visible candidates, not to recover missing
index coverage.

## When To Use It

Use target selection when:

- retrieval Top-K contains the right tool but the LLM may choose a sibling
- list, detail, count, and mutation operations have similar names
- operation names are similar but request or response contracts differ
- a product UI needs to explain LLM override decisions
- Quality Lab needs a stable plan hit signal
- promoted trace-learning evidence should influence ranking without dominating
  base retrieval

Do not use selector overrides to hide poor retrieval. If the expected tool is
not in the candidate set, improve OpenAPI semantic build, aliases, contract
extraction, or graph edges first.

## Public API

`select_target_candidate()` is product-neutral. It reads generic tool metadata,
retrieval evidence, and optional promoted learning suggestions.

<Tabs>
  <TabItem value="basic" label="Basic" default>

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="find refund-ready order details",
    candidates=candidate_names,
    tools=tools_by_name,
)

print(selection["selected_target"])
print(selection["reason_codes"])
```

  </TabItem>
  <TabItem value="with-llm" label="With LLM target">

```python
from graph_tool_call.graphify import retrieve_graphify, select_target_candidate

retrieval = retrieve_graphify(
    graph_json,
    "회원 배송지 상세 조회",
    top_k=8,
    include_evidence=True,
)

selection = select_target_candidate(
    query="회원 배송지 상세 조회",
    candidates=retrieval["results"],
    tools=graph_json["tools"],
    retrieval_results=retrieval["results"],
    llm_target="getMemberDeliveryList",
    policy="strong_evidence",
)
```

  </TabItem>
  <TabItem value="learning" label="With learning">

```python
selection = select_target_candidate(
    query=query,
    candidates=retrieval_rows,
    tools=tools_by_name,
    retrieval_results=retrieval_rows,
    llm_target=intent.target,
    learning_suggestions=promoted_suggestions,
)

if selection["learning_applied"]:
    audit(selection["rank_signals"])
```

  </TabItem>
</Tabs>

## Input Contract

| Parameter | Type | Required | Meaning |
| --- | --- | --- | --- |
| `query` | `str` | yes | Original user request |
| `candidates` | `list[str]` or `list[dict]` | yes | Retrieved candidate names or retrieval rows |
| `tools` | `dict[str, Any]` | yes | Tool dictionary keyed by tool name |
| `retrieval_results` | `list[dict]` | no | Evidence-rich retrieval rows from `retrieve_graphify()` |
| `llm_target` | `str` | no | Target selected by the LLM intent step |
| `learning_suggestions` | `list[dict]` | no | Promoted collection-scoped trace-learning suggestions |
| `policy` | `str` | no | Default is `strong_evidence` |

The selector ignores candidates that are not present in `tools`. If `llm_target`
is not in the candidate list but exists in `tools`, it is added to the comparison
set so the final decision can explain the disagreement.

## Output Schema

The return value is a plain dictionary so adapters can store it directly in
intent metadata, plan metadata, Quality Lab results, and trace records.

```json
{
  "selected_target": "getOrderDetail",
  "llm_target": "getGeneralOrderInfo",
  "confidence": 0.87,
  "overrode_llm": true,
  "ambiguous": false,
  "reason_codes": [
    "llm_target_overridden"
  ],
  "margin": 0.19,
  "llm_margin": 0.19,
  "policy": "strong_evidence",
  "rank_signals": [],
  "candidate_evidence": [],
  "target_action_priority": {
    "read": 3,
    "search": 2
  },
  "result_shape_priority": {
    "single": 3,
    "list": 1
  },
  "learning_applied": false
}
```

| Field | Meaning |
| --- | --- |
| `selected_target` | Final selected tool name |
| `llm_target` | Original LLM target when supplied |
| `confidence` | Selector score of the final target |
| `overrode_llm` | Whether deterministic evidence replaced the LLM target |
| `ambiguous` | Whether the margin was weak or candidates were too close |
| `reason_codes` | Stable diagnostic reason codes |
| `margin` | Difference between the top two selector scores |
| `llm_margin` | Difference between the deterministic winner and the LLM target |
| `rank_signals` | Per-candidate scoring rows with selected and LLM flags |
| `candidate_evidence` | Compact evidence per candidate |
| `target_action_priority` | Query-derived action preferences |
| `result_shape_priority` | Query-derived result-shape preferences |
| `learning_applied` | Whether promoted learning suggestions affected scoring |

The numeric score is useful for relative comparison inside one selector run. Do
not treat absolute score values as a public compatibility contract.

## Ranking Signals

The selector combines retrieval position with deterministic evidence from the
collection artifact.

| Signal | Source | What It Helps With |
| --- | --- | --- |
| retrieval rank | `candidates`, `retrieval_results` | keeps the retrieval engine as the base ordering |
| operation surface | name, operation id, summary, description | direct query and identifier matches |
| `canonical_action` | semantic metadata | read vs search vs mutation confusion |
| `primary_resource` | semantic metadata | business object alignment |
| `path_module` | OpenAPI metadata | large API module scoping |
| `result_shape` | semantic metadata or surface inference | list/detail/count/mutation siblings |
| contract fit | `metadata.api_contract` | required/request/response field alignment |
| learning | promoted suggestions | validated local feedback as a low-weight boost |

Good selector decisions usually have more than one supporting signal. A single
weak text match should not override an LLM target.

## Override Policy

The default `strong_evidence` policy is intentionally conservative.

| Condition | Behavior |
| --- | --- |
| No candidates are valid | return `no_candidates` |
| LLM target is also the deterministic winner | keep it |
| LLM target differs, winner has strong evidence, and margin is large enough | override |
| LLM target differs but margin is weak | keep LLM target and mark `ambiguous_target` |
| Top candidates are too close | mark ambiguity or tie |
| LLM target is outside candidates and unknown | report `llm_target_not_in_candidates` |

The library uses a fixed margin threshold for safe override. Product adapters
should not lower that threshold casually. If operators want more aggressive
behavior, first prove it with Quality Lab cases.

## Reason Codes

| Reason | Meaning | Typical Next Step |
| --- | --- | --- |
| `selected_by_strong_evidence` | Deterministic evidence selected the winner | proceed to plan synthesis |
| `selected_by_rank` | Ranking selected the winner without strong evidence | inspect evidence before relying on it for critical flows |
| `llm_target_overridden` | Strong evidence replaced the LLM target | store selector block for audit |
| `llm_target_preserved` | LLM target was kept even though another candidate ranked higher | inspect margin and ambiguity |
| `llm_target_not_in_candidates` | LLM selected a tool outside the visible candidate set | check catalog prompt and tool visibility |
| `ambiguous_target` | Candidate scores were too close for a confident override | add metadata, aliases, or contract evidence |
| `candidate_tie` | Top candidates are effectively tied | add a Quality Lab case or operator hint |
| `no_candidates` | No selectable candidates were available | fix retrieval or source ingestion |

Reason codes are stable enough to store in product logs and Quality Lab results.

## Example: Detail vs List Sibling

Large enterprise OpenAPI catalogs often contain siblings such as:

| Tool | Action | Resource | Shape |
| --- | --- | --- | --- |
| `getMemberDeliveryList` | `search` or `read` | `member_delivery` | `list` |
| `getMemberDeliveryDetail` | `read` | `member_delivery` | `single` |
| `getMemberInfo` | `read` | `member` | `single` |

For a detail query, the selector should prefer the detail operation only when
shape, resource, and contract evidence agree.

```python
selection = select_target_candidate(
    query="회원 배송지 상세 정보를 조회해줘",
    candidates=[
        "getMemberDeliveryList",
        "getMemberDeliveryDetail",
        "getMemberInfo",
    ],
    tools=tools_by_name,
    retrieval_results=retrieval_results,
    llm_target="getMemberDeliveryList",
)

assert selection["selected_target"] == "getMemberDeliveryDetail"
assert selection["overrode_llm"] is True
assert "llm_target_overridden" in selection["reason_codes"]
```

If the selector cannot see the `single` shape or the response fields, it should
not force an override. Fix semantic metadata or contract extraction first.

## Example: Weak Margin

When two candidates are too close, ambiguity is a feature, not a bug.

```python
selection = select_target_candidate(
    query="주문 정보 조회",
    candidates=["getOrderInfo", "getOrderSummary"],
    tools=tools_by_name,
    llm_target="getOrderSummary",
)

if selection["ambiguous"]:
    show_operator_debug(selection["candidate_evidence"])
```

This tells the adapter to keep the result explainable and avoid pretending the
engine had stronger evidence than it did.

## Adapter Integration

Product adapters should run target selection in both online flows and regression
suites.

| Integration Point | What To Store |
| --- | --- |
| intent result | `llm_target`, `selected_target`, `overrode_llm` |
| plan metadata | complete `target_selector` block |
| Quality Lab result | selector outcome, reason codes, rank signals |
| trace learning record | scrubbed selector block |
| UI diagnostics | compact evidence comparison |

Recommended flow:

```python
retrieval = retrieve_graphify(graph_json, query, top_k=8, include_evidence=True)
intent = parse_intent(query, catalog=retrieval["results"], llm=llm)

selection = select_target_candidate(
    query=query,
    candidates=retrieval["results"],
    tools=graph_json["tools"],
    retrieval_results=retrieval["results"],
    llm_target=intent.target,
    learning_suggestions=promoted_suggestions,
)

plan = synthesizer.synthesize(
    target=selection["selected_target"],
    entities=intent.entities,
    goal=query,
)
plan.metadata.setdefault("synthesis", {})["target_selector"] = selection
```

Adapters should pass a compact selector-ranked catalog to the LLM. That keeps
the prompt small and makes the LLM see the same candidates the deterministic
selector will audit.

## UI Display Contract

Do not show the full raw tool metadata in a product UI. Show a comparison table.

| UI Field | Source |
| --- | --- |
| final target | `selected_target` |
| LLM target | `llm_target` |
| override badge | `overrode_llm` |
| uncertainty badge | `ambiguous`, `reason_codes` |
| matched action/resource/shape | candidate evidence and rank signals |
| matched fields | contract evidence |
| learning boost | `learning_applied` and learning signal row |

For a failed run, this lets the operator see whether the problem was retrieval,
LLM target selection, plan inputs, auth readiness, or downstream API execution.

## Quality Checks

Add selector regression cases whenever you introduce a new semantic rule or
change retrieval scoring.

| Check | Expected Result |
| --- | --- |
| exact target match | selected target equals expected target |
| weak margin | LLM target is preserved and `ambiguous_target` is recorded |
| strong evidence override | selector overrides the wrong LLM sibling |
| list/detail sibling | detail query chooses `single`; list query chooses `list` |
| Korean query with English operation id | mixed-language query still selects expected tool |
| promoted learning boost | boost improves rank but does not dominate weak evidence |

Useful commands:

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_xgen_tool_graph_benchmark.py -q
```

For product validation, run Quality Lab plan cases and compare:

- search hit@K
- LLM target
- selected target
- override rate
- ambiguous rate
- plan hit rate

## Operational Guidance

Treat selector output as evidence, not magic. A healthy large collection should
show:

- expected target present in Top-K
- strong selector evidence for important plan cases
- low ambiguity for high-frequency workflows
- override decisions backed by semantic and contract evidence
- Quality Lab fixtures that cover sibling operations
- promoted learning suggestions visible as low-weight rank signals

If all candidates have `unknown` action, `unassigned` resource, or missing
contracts, the selector cannot make reliable decisions. Rebuild the OpenAPI
collection with semantic metadata and contract extraction enabled.

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Evidence Output](./evidence-output.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
