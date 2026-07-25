---
title: Target Selection
description: retrieved candidate에서 최종 tool을 선택하고 약한 LLM 선택을 guard합니다.
---

# Target Selection

Target selection은 retrieval 이후 최종 tool을 선택합니다. ranked candidate evidence와
선택적으로 전달된 LLM-selected target을 비교하고 structured decision을 반환합니다.

selector는 LLM을 대체하지 않습니다. guardrail 역할을 합니다. deterministic evidence가
강하고 LLM target이 명확히 약하면 override할 수 있습니다. margin이 약하면 LLM target을
유지하고 ambiguity를 기록합니다.

## 언제 사용하나

다음 상황에서 사용합니다.

- retrieval Top-K 안에는 정답 tool이 있지만 LLM이 sibling을 고를 수 있음
- list/detail/count/mutation operation이 혼동되기 쉬움
- operation name은 비슷하지만 contract가 다름
- product UI에서 LLM override 여부를 설명해야 함
- Quality Lab이 stable plan hit signal을 필요로 함

정답 tool이 Top-K에 없다면 selector override로 숨기지 말고 indexing, semantic
metadata, contract, alias를 먼저 개선합니다.

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
| `query` | `str` | user request |
| `candidates` | `list[str]` or `list[dict]` | retrieved candidate name 또는 result row |
| `tools` | `dict[str, Any]` | tool name으로 keyed된 tool dictionary |
| `retrieval_results` | `list[dict]` | optional evidence-rich retrieval rows |
| `llm_target` | `str | None` | LLM이 선택한 target |
| `learning_suggestions` | `list[dict] | None` | optional promoted learning suggestions |
| `policy` | `str` | 기본값 `strong_evidence` |

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
| `selected_target` | final selected tool |
| `confidence` | selector confidence |
| `overrode_llm` | LLM target이 변경됐는지 |
| `ambiguous` | evidence margin이 약했는지 |
| `reason_codes` | stable diagnostic reasons |
| `rank_signals` | decision에 사용된 evidence |
| `candidate_evidence` | candidate별 evidence summary |
| `llm_target` | 전달된 original LLM target |
| `policy` | 적용된 selector policy |

## Ranking Evidence

selector는 tool metadata와 retrieval result에서 evidence를 읽습니다.

- retrieval rank and score
- operation id/name/summary exact or partial match
- `canonical_action`
- `primary_resource`
- `path_module`
- `result_shape`
- request/response contract fit
- promoted learning suggestions

기본 정책은 conservative합니다. winner가 strong evidence를 갖고 LLM target 대비
충분한 margin이 있을 때만 override해야 합니다.

## Common Reason Codes

| Reason | Meaning |
| --- | --- |
| `selected_by_strong_evidence` | deterministic evidence로 winner 선택 |
| `selected_by_rank` | strong evidence 없이 ranking으로 선택 |
| `llm_target_overridden` | strong evidence가 LLM target을 대체 |
| `llm_target_preserved` | LLM target 유지 |
| `llm_target_not_in_candidates` | LLM이 candidate set 밖의 tool을 선택 |
| `ambiguous_target` | evidence margin이 약함 |
| `candidate_tie` | top candidate가 너무 가까움 |
| `no_candidates` | 선택 가능한 candidate가 없음 |

## 예제: Detail vs General Sibling

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

detail candidate가 shape, resource, contract evidence에서 더 강할 때만 이런 override가
일어나야 합니다.

## Adapter Notes

Product adapter는 selector block을 intent, plan, Quality Lab, trace metadata에
저장하는 것이 좋습니다.

- `selected_target`
- `llm_target`
- `overrode_llm`
- `ambiguous`
- `reason_codes`
- `rank_signals`

이렇게 해야 실패 실행을 디버깅할 수 있습니다. strong selector choice 이후 실행이
실패했다면 원인은 target selection보다 plan input, auth readiness, downstream API일
가능성이 큽니다.

## Quality Checks

selector regression test는 아래 케이스를 포함하는 것이 좋습니다.

- exact target match
- weak margin ambiguity
- strong evidence 기반 LLM override
- list/detail sibling confusion
- Korean query with English operation id
- weak evidence를 지배하지 않는 promoted learning boost

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Quality Lab](../validation/quality-lab.md)
