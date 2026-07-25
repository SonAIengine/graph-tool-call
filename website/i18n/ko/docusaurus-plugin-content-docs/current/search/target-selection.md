---
title: Target 선택
description: deterministic evidence와 LLM guardrail로 retrieved candidate에서 최종 tool을 선택합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Target 선택

Target selection은 retrieval과 plan synthesis 사이의 결정 계층입니다. 작은
candidate set을 받아 semantic evidence와 contract evidence를 비교하고, 실제 plan에
넘길 최종 tool을 반환합니다.

selector는 LLM을 대체하지 않습니다. LLM이 더 안전한 범위 안에서 판단하도록
guardrail을 제공합니다. deterministic evidence가 강하고 LLM이 약한 sibling tool을
골랐다면 override할 수 있습니다. evidence가 비슷하면 LLM target을 유지하고
ambiguity를 기록합니다.

특정 tool이 왜 선택됐는지, LLM target이 왜 override됐는지, Quality Lab에서 검색은
통과했는데 plan이 왜 실패했는지 설명해야 할 때 이 페이지를 기준으로 보면 됩니다.

## 어디에서 실행되나

selector는 graph retrieval 이후, `PathSynthesizer` 이전에 실행됩니다.

| Stage | Input | Output | Failure Signal |
| --- | --- | --- | --- |
| Retrieve | query, graph artifact | ranked candidates | expected tool이 Top-K에 없음 |
| LLM intent | query, compact catalog | optional `llm_target` | LLM이 sibling 또는 외부 tool 선택 |
| Select | query, candidates, evidence | `target_selector` block | `ambiguous_target`, `no_candidates` |
| Plan | selected target, entities | executable `Plan` | `unsatisfied_field`, `enum_required` |
| Execute | plan, adapter auth | runner events | auth/API/request failure |

정답 tool이 retrieval Top-K에 없다면 search부터 고쳐야 합니다. Target selection은
보이는 candidate 중에서 고르는 계층이지, index coverage가 빠진 tool을 복구하는 계층이
아닙니다.

## 언제 사용하나

다음 상황에서 사용합니다.

- retrieval Top-K 안에는 정답 tool이 있지만 LLM이 sibling을 고를 수 있음
- list, detail, count, mutation operation 이름이 비슷함
- operation name은 비슷하지만 request/response contract가 다름
- product UI에서 LLM override 여부를 설명해야 함
- Quality Lab에서 stable plan hit signal이 필요함
- promoted trace-learning evidence를 base retrieval을 압도하지 않는 low-weight signal로
  반영해야 함

정답 tool이 candidate set에 없다면 selector override로 숨기지 말고 OpenAPI semantic
build, alias, contract extraction, graph edge를 먼저 개선합니다.

## Public API

`select_target_candidate()`는 product-neutral API입니다. generic tool metadata,
retrieval evidence, optional promoted learning suggestion만 읽습니다.

<Tabs>
  <TabItem value="basic" label="기본" default>

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
  <TabItem value="with-llm" label="LLM target 포함">

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
  <TabItem value="learning" label="Learning 포함">

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
| `query` | `str` | yes | 원본 user request |
| `candidates` | `list[str]` or `list[dict]` | yes | retrieved candidate name 또는 retrieval row |
| `tools` | `dict[str, Any]` | yes | tool name으로 keyed된 tool dictionary |
| `retrieval_results` | `list[dict]` | no | `retrieve_graphify()`가 반환한 evidence-rich retrieval row |
| `llm_target` | `str` | no | LLM intent 단계가 선택한 target |
| `learning_suggestions` | `list[dict]` | no | promoted collection-scoped trace-learning suggestion |
| `policy` | `str` | no | 기본값 `strong_evidence` |

selector는 `tools`에 없는 candidate를 무시합니다. `llm_target`이 candidate list에는
없지만 `tools`에는 있으면 비교 set에 추가해서 disagreement를 설명할 수 있게 합니다.

## Output Schema

반환값은 plain dictionary입니다. Adapter는 이 값을 intent metadata, plan metadata,
Quality Lab result, trace record에 그대로 저장할 수 있습니다.

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

| Field | 의미 |
| --- | --- |
| `selected_target` | 최종 selected tool name |
| `llm_target` | 전달된 original LLM target |
| `confidence` | final target의 selector score |
| `overrode_llm` | deterministic evidence가 LLM target을 바꿨는지 |
| `ambiguous` | margin이 약하거나 candidate가 너무 가까웠는지 |
| `reason_codes` | stable diagnostic reason code |
| `margin` | top two selector score 차이 |
| `llm_margin` | deterministic winner와 LLM target의 score 차이 |
| `rank_signals` | selected/LLM flag가 포함된 candidate scoring row |
| `candidate_evidence` | candidate별 compact evidence |
| `target_action_priority` | query에서 추론한 action preference |
| `result_shape_priority` | query에서 추론한 result-shape preference |
| `learning_applied` | promoted learning suggestion이 scoring에 반영됐는지 |

숫자 score는 한 번의 selector run 안에서 상대 비교에 유용합니다. absolute score 값을
public compatibility contract로 취급하지 마세요.

## Ranking Signals

selector는 retrieval position과 collection artifact의 deterministic evidence를 함께
사용합니다.

| Signal | Source | 도움이 되는 상황 |
| --- | --- | --- |
| retrieval rank | `candidates`, `retrieval_results` | retrieval engine의 base ordering 유지 |
| operation surface | name, operation id, summary, description | 직접적인 query/identifier match |
| `canonical_action` | semantic metadata | read/search/mutation 혼동 분리 |
| `primary_resource` | semantic metadata | 비즈니스 객체 정렬 |
| `path_module` | OpenAPI metadata | 대형 API module scoping |
| `result_shape` | semantic metadata 또는 surface inference | list/detail/count/mutation sibling 분리 |
| contract fit | `metadata.api_contract` | required/request/response field alignment |
| learning | promoted suggestions | 검증된 local feedback을 low-weight boost로 반영 |

좋은 selector decision은 보통 둘 이상의 supporting signal을 가집니다. 단일 약한 text
match만으로 LLM target을 override하면 안 됩니다.

## Override 정책

기본 `strong_evidence` 정책은 보수적입니다.

| Condition | Behavior |
| --- | --- |
| valid candidate가 없음 | `no_candidates` 반환 |
| LLM target이 deterministic winner와 같음 | 그대로 유지 |
| LLM target이 다르고 winner evidence가 강하며 margin이 충분함 | override |
| LLM target이 다르지만 margin이 약함 | LLM target 유지, `ambiguous_target` 기록 |
| top candidate가 너무 가까움 | ambiguity 또는 tie 기록 |
| LLM target이 candidate 밖이고 unknown | `llm_target_not_in_candidates` 기록 |

라이브러리는 안전한 override를 위해 fixed margin threshold를 사용합니다. Product adapter가
임의로 이 threshold를 낮추기보다는 Quality Lab case로 먼저 증명해야 합니다.

## Reason Codes

| Reason | 의미 | 다음 확인 |
| --- | --- | --- |
| `selected_by_strong_evidence` | deterministic evidence로 winner 선택 | plan synthesis 진행 |
| `selected_by_rank` | strong evidence 없이 ranking으로 선택 | critical flow에서는 evidence 확인 |
| `llm_target_overridden` | strong evidence가 LLM target을 대체 | selector block 저장 |
| `llm_target_preserved` | 다른 candidate가 더 높아도 LLM target 유지 | margin과 ambiguity 확인 |
| `llm_target_not_in_candidates` | LLM이 visible candidate 밖의 tool 선택 | catalog prompt와 tool visibility 확인 |
| `ambiguous_target` | candidate score가 너무 가까움 | metadata, alias, contract evidence 보강 |
| `candidate_tie` | top candidate가 사실상 동률 | Quality Lab case 또는 operator hint 추가 |
| `no_candidates` | 선택 가능한 candidate 없음 | retrieval 또는 source ingest 수정 |

Reason code는 product log와 Quality Lab result에 저장할 수 있을 정도로 안정적인 계약입니다.

## 예제: Detail vs List Sibling

대형 엔터프라이즈 OpenAPI catalog에는 아래처럼 sibling operation이 자주 있습니다.

| Tool | Action | Resource | Shape |
| --- | --- | --- | --- |
| `getMemberDeliveryList` | `search` 또는 `read` | `member_delivery` | `list` |
| `getMemberDeliveryDetail` | `read` | `member_delivery` | `single` |
| `getMemberInfo` | `read` | `member` | `single` |

상세 조회 query에서는 shape, resource, contract evidence가 함께 맞을 때만 detail operation을
우선해야 합니다.

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

selector가 `single` shape나 response field를 보지 못한다면 강제 override하면 안 됩니다.
먼저 semantic metadata나 contract extraction을 고쳐야 합니다.

## 예제: 약한 Margin

candidate가 너무 가까우면 ambiguity는 문제라기보다 안전 장치입니다.

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

이 결과는 adapter에게 “강한 evidence가 있었던 것처럼 보이게 하지 말라”고 알려줍니다.

## Adapter Integration

Product adapter는 online flow와 regression suite 양쪽에서 target selection을 실행하는 것이
좋습니다.

| Integration Point | 저장할 내용 |
| --- | --- |
| intent result | `llm_target`, `selected_target`, `overrode_llm` |
| plan metadata | complete `target_selector` block |
| Quality Lab result | selector outcome, reason codes, rank signals |
| trace learning record | scrubbed selector block |
| UI diagnostics | compact evidence comparison |

권장 흐름:

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

Adapter는 selector-ranked compact catalog를 LLM에 넘기는 것이 좋습니다. 그래야 prompt가
작아지고, LLM이 보는 candidate와 deterministic selector가 audit하는 candidate가
같아집니다.

## UI Display Contract

Product UI에는 raw tool metadata 전체를 보여주지 말고 비교 표를 보여주세요.

| UI Field | Source |
| --- | --- |
| final target | `selected_target` |
| LLM target | `llm_target` |
| override badge | `overrode_llm` |
| uncertainty badge | `ambiguous`, `reason_codes` |
| matched action/resource/shape | candidate evidence and rank signals |
| matched fields | contract evidence |
| learning boost | `learning_applied` and learning signal row |

실패 실행에서는 이 정보로 문제가 retrieval, LLM target selection, plan input, auth
readiness, downstream API execution 중 어디에 있는지 구분할 수 있습니다.

## Quality Checks

새 semantic rule을 추가하거나 retrieval scoring을 바꿀 때는 selector regression case를
추가하세요.

| Check | Expected Result |
| --- | --- |
| exact target match | selected target equals expected target |
| weak margin | LLM target 유지, `ambiguous_target` 기록 |
| strong evidence override | 잘못된 LLM sibling을 selector가 override |
| list/detail sibling | detail query는 `single`, list query는 `list` 선택 |
| Korean query with English operation id | mixed-language query도 expected tool 선택 |
| promoted learning boost | rank 개선은 하되 weak evidence를 압도하지 않음 |

유용한 명령:

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_xgen_tool_graph_benchmark.py -q
```

Product validation에서는 Quality Lab plan case를 돌리고 아래를 비교합니다.

- search hit@K
- LLM target
- selected target
- override rate
- ambiguous rate
- plan hit rate

## 운영 가이드

selector output은 magic이 아니라 evidence입니다. 건강한 대형 collection은 아래 상태를
보여야 합니다.

- expected target이 Top-K에 있음
- 중요한 plan case에서 strong selector evidence가 있음
- high-frequency workflow의 ambiguity가 낮음
- override decision이 semantic/contract evidence로 설명됨
- sibling operation을 포함하는 Quality Lab fixture가 있음
- promoted learning suggestion이 low-weight rank signal로 보임

모든 candidate가 `unknown` action, `unassigned` resource, missing contract 상태라면
selector는 신뢰할 수 있는 결정을 만들 수 없습니다. semantic metadata와 contract
extraction을 켠 상태로 OpenAPI collection을 다시 build하세요.

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Evidence Output](./evidence-output.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
