---
title: Target Selection
description: Select a final tool from retrieved candidates while guarding weak LLM choices.
---

# Target Selection

Target selection chooses the final tool after retrieval. It compares ranked
candidate evidence with an optional LLM-selected target and returns a structured
decision.

The selector does not replace the LLM. It acts as a guardrail: if deterministic
evidence is strong and the LLM target is clearly weaker, it can override. If the
margin is weak, it keeps the LLM target and records ambiguity.

## When To Use This

Use target selection when:

- retrieval Top-K contains the correct tool but the LLM may choose a sibling
- list/detail/count/mutation operations are easy to confuse
- operation names are similar but contracts differ
- a product UI needs to explain whether the LLM was overridden
- Quality Lab needs a stable plan hit signal

Do not use selector overrides to hide poor retrieval. If the correct tool is not
in Top-K, improve indexing, semantic metadata, contracts, or aliases first.

## Public API

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="find refund-ready order details",
    candidates=candidate_names,
    tools=tools_by_name,
    retrieval_results=retrieval_results,
    llm_target=llm_target,
    policy="strong_evidence",
)
```

## Inputs

| Parameter | Type | Meaning |
| --- | --- | --- |
| `query` | `str` | User request |
| `candidates` | `list[str]` or `list[dict]` | Retrieved candidate names or result rows |
| `tools` | `dict[str, Any]` | Tool dictionary keyed by tool name |
| `retrieval_results` | `list[dict]` | Optional evidence-rich retrieval rows |
| `llm_target` | `str | None` | Target selected by the LLM |
| `learning_suggestions` | `list[dict] | None` | Optional promoted learning suggestions |
| `policy` | `str` | Default is `strong_evidence` |

## Output

```python
{
    "selected_target": "getOrderDetail",
    "confidence": 0.87,
    "overrode_llm": True,
    "ambiguous": False,
    "reason_codes": ["llm_target_overridden"],
    "rank_signals": [...],
    "candidate_evidence": [...],
    "llm_target": "getGeneralOrderInfo",
    "policy": "strong_evidence",
}
```

| Field | Meaning |
| --- | --- |
| `selected_target` | Final selected tool |
| `confidence` | Selector confidence |
| `overrode_llm` | Whether the LLM target was changed |
| `ambiguous` | Whether evidence margin was weak |
| `reason_codes` | Stable diagnostic reasons |
| `rank_signals` | Evidence used for the decision |
| `candidate_evidence` | Per-candidate evidence summary |
| `llm_target` | Original LLM target when supplied |
| `policy` | Applied selector policy |

## Ranking Evidence

The selector reads evidence from tool metadata and retrieval results:

- retrieval rank and score
- operation id/name/summary exact or partial match
- `canonical_action`
- `primary_resource`
- `path_module`
- `result_shape`
- request and response contract fit
- promoted learning suggestions

The default policy is conservative. It should override only when the winner has
strong evidence and enough margin over the LLM target.

## Common Reason Codes

| Reason | Meaning |
| --- | --- |
| `selected_by_strong_evidence` | Deterministic evidence selected the winner |
| `selected_by_rank` | Ranking selected the winner without strong evidence |
| `llm_target_overridden` | Strong evidence replaced the LLM target |
| `llm_target_preserved` | LLM target was kept |
| `llm_target_not_in_candidates` | LLM selected a tool outside the candidate set |
| `ambiguous_target` | Evidence margin was too weak |
| `candidate_tie` | Top candidates were too close |
| `no_candidates` | No selectable candidates were available |

## Example: Detail vs General Sibling

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
```

This should happen only when the detail candidate has stronger shape, resource,
and contract evidence.

## Adapter Notes

Product adapters should store the selector block in intent, plan, Quality Lab,
and trace metadata:

- `selected_target`
- `llm_target`
- `overrode_llm`
- `ambiguous`
- `reason_codes`
- `rank_signals`

That makes failed runs debuggable. If execution fails after a strong selector
choice, the likely problem is plan inputs, auth readiness, or the downstream
API, not target selection.

## Quality Checks

Write selector regression tests for:

- exact target match
- weak margin ambiguity
- LLM override with strong evidence
- list/detail sibling confusion
- Korean query with English operation id
- promoted learning boost that does not dominate weak evidence

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Quality Lab](../validation/quality-lab.md)
