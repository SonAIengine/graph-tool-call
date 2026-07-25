---
title: 학습 제안
description: scrub된 execution trace를 collection-scoped learning suggestion으로 변환합니다.
---

# 학습 제안

Learning suggestion은 scrub된 execution trace에서 도출한 graph, search, selector,
planning 개선 후보입니다.

기본적으로 production truth가 아닙니다. Suggestion은 관찰된 evidence로 시작하고,
collection 범위 안에 머물며, promotion 이후에만 ranking에 영향을 줍니다.

## 언제 사용하는가

실행 결과가 재사용 가능한 사실을 알려줄 때 suggestion을 사용합니다.

- 같은 query family가 반복적으로 같은 target을 선택함
- 첫 target 실패 후 retry에서 성공함
- plan path가 선택된 target을 안정적으로 만족함
- runtime trace가 두 tool 사이의 data-flow edge를 증명함
- operator가 field mapping, context default, enum mapping을 승인함

일회성 실패를 땜질하거나, raw payload를 저장하거나, product-specific shortcut을 엔진에
넣는 용도로 쓰지 않습니다.

## Public API

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    learning_signal_map,
    merge_learning_suggestions,
    summarize_learning_state,
)
```

이 helper들은 storage-neutral입니다. 반환 dict는 collection artifact, JSONB row, file,
product-specific store 어디에든 저장할 수 있습니다.

## Suggestion Types

| Type | Core Helper 생성 | 의미 | 주 사용처 |
| --- | --- | --- | --- |
| `target_preference` | yes | 이 query family가 특정 target을 성공적으로 선택함 | retrieval과 target selector |
| `plan_path` | yes | 이 ordered tool path가 성공적으로 완료됨 | plan synthesis |
| `data_flow_edge` | yes | runtime trace가 tool 간 useful data flow를 관찰함 | graph expansion과 planner |
| `field_mapping` | adapter/operator | source field가 target field로 매핑됨 | request binding |
| `context_default_candidate` | adapter/operator | stable context 값으로 user prompt를 줄일 수 있음 | adapter settings |
| `enum_mapping_candidate` | adapter/operator | value-label enum mapping을 재사용할 수 있음 | enum binding UI |

앞의 세 가지는 `derive_learning_suggestions()`가 직접 생성합니다. 나머지는 adapter가 검토한
signal을 별도 schema 없이 저장할 수 있도록 public vocabulary에 포함되어 있습니다.

## Learning Record 만들기

Search, plan, execute attempt 이후 record를 만듭니다. 성공 record는 suggestion을 만들고,
실패 record는 promotion guard로 사용합니다.

```python
from graph_tool_call.learning import build_trace_learning_record

record = build_trace_learning_record(
    query="환불 가능한 주문을 찾아줘",
    collection_id="bo-dev",
    attempt_id="attempt-001",
    session_id="session-raw-value",
    selected_target="getRefundableOrders",
    llm_target="getOrderDetail",
    plan_tools=["searchOrders", "getRefundableOrders"],
    success=True,
    latency_ms=1430,
    target_selector={
        "selected_target": "getRefundableOrders",
        "overrode_llm": True,
        "reason_codes": ["shape_match"],
    },
    trace_edges=[
        {
            "source": "searchOrders",
            "target": "getRefundableOrders",
            "data_flow": {"to_field": "orderNo"},
        }
    ],
)
```

반환 record에는 다음 정보가 들어갑니다.

| Field | Notes |
| --- | --- |
| `query_family` | normalized query grouping key |
| `query_fingerprint` | future query match에 쓰는 stable hash |
| `session_id_hash` | raw session id가 아닌 hash |
| `target_selector` | scrub된 selector diagnostics |
| `trace_edges` | scrub된 run-observed edge evidence |
| `failure_reason` | failed attempt와 promotion gate에 사용 |

## Suggestion 도출

```python
from graph_tool_call.learning import derive_learning_suggestions

new_suggestions = derive_learning_suggestions(
    record,
    history=previous_attempts,
    existing_suggestions=current_suggestions,
    promotion_policy={
        "min_success_observations": 2,
        "max_recent_failure_ratio": 0.5,
    },
)
```

`derive_learning_suggestions()`는 입력 record로 생성 또는 갱신된 suggestion만 반환합니다.
Adapter가 collection 전체 suggestion list를 관리할 때는 `merge_learning_suggestions()`를
사용합니다.

```python
from graph_tool_call.learning import merge_learning_suggestions

collection_suggestions = merge_learning_suggestions(
    existing=current_suggestions,
    incoming=new_suggestions,
    history=[*previous_attempts, record],
)
```

## Suggestion Shape

저장된 target preference suggestion 예시입니다.

```json
{
  "id": "target_preference:3f9d6dd00a0e50c1",
  "type": "target_preference",
  "collection_id": "bo-dev",
  "query_family": "환불 가능한 주문을 찾아줘",
  "query_fingerprint": "84cc9f99591e3f3d",
  "target": "getRefundableOrders",
  "status": "suggested",
  "observations": 1,
  "prior_failure_count": 0,
  "evidence_sources": ["run"],
  "evidence": {
    "selected_target": "getRefundableOrders",
    "llm_target": "getOrderDetail",
    "target_selector": {
      "overrode_llm": true,
      "reason_codes": ["shape_match"]
    }
  }
}
```

알 수 없는 field는 additive로 취급합니다. Consumer는 forwarding이나 rendering 시 unknown
metadata를 보존하는 편이 안전합니다.

## Status Lifecycle

| Status | Ranking 영향 | 의미 |
| --- | --- | --- |
| `suggested` | 없음 | 관찰됐지만 ranking에 반영할 준비는 안 됨 |
| `promotable` | 기본적으로 없음 | 반복 성공 또는 policy gate로 promotion 가능 |
| `promoted` | low-weight boost | operator 또는 policy가 ranking/selector 반영 허용 |
| `rejected` | 없음 | operator 또는 policy가 사용하지 않기로 결정 |

기본 policy는 matching success 2회 이상을 요구합니다. 최근 failure ratio가 `0.5`를 넘으면
promotion에서 제외해야 합니다.

## Learning Signal 적용

```python
from graph_tool_call.learning import apply_learning_suggestions

result = apply_learning_suggestions(
    query="환불 가능한 주문을 찾아줘",
    candidates=[
        {"name": "getOrderDetail", "score": 0.72},
        {"name": "getRefundableOrders", "score": 0.71},
    ],
    suggestions=collection_suggestions,
    mode="promoted",
)
```

출력 예시:

```json
{
  "applied_count": 1,
  "mode": "promoted",
  "signals": [
    {
      "source": "learning",
      "target": "getRefundableOrders",
      "suggestion_type": "target_preference",
      "status": "promoted",
      "observations": 3,
      "score": 0.045
    }
  ]
}
```

Learning boost는 의도적으로 작습니다. 가까운 후보를 조금 올리는 용도이지, 강한 semantic,
contract, exact-match evidence를 뒤집는 용도가 아닙니다.

## Shadow Comparison

Promotion 전에 shadow comparison을 실행합니다.

```python
shadow = apply_learning_suggestions(
    query=query,
    candidates=current_candidates,
    suggestions=collection_suggestions,
    mode="shadow",
)
```

비교할 metric:

| Metric | 목적 |
| --- | --- |
| `current_rank` | learning 없는 rank |
| `shadow_rank` | suggested/promotable learning을 적용한 rank |
| `rank_delta` | expected target이 위로 올라갔는지 |
| `selected_target_changed` | learning이 behavior를 바꾸는지 |
| `allowed_failure_reason` | 기존 failure가 예상 가능한 실패였는지 |

Shadow 결과가 원하는 target을 개선하고 ambiguous/unsafe behavior를 만들지 않을 때만
promotion합니다.

## Product UI Guidance

운영자가 확신을 가지고 승인/거절할 수 있는 정보를 보여줘야 합니다.

| UI Field | 중요한 이유 |
| --- | --- |
| query family | 재사용 범위를 보여줌 |
| suggestion type | 무엇이 바뀌는지 설명 |
| target 또는 plan path | 영향받는 behavior 표시 |
| observations | 단일 성공이 아님을 증명 |
| prior failures | 불안정한 evidence 경고 |
| status | ranking 반영 여부 표시 |
| evidence source | run/manual/policy evidence 분리 |
| shadow rank delta | 예상 품질 영향 표시 |
| promote/reject controls | risky collection에서 human-in-the-loop 유지 |

## Safety Checklist

Promotion 전에 확인합니다.

1. Suggestion이 collection-scoped인지 확인합니다.
2. Raw request/response body가 없는지 확인합니다.
3. Token, cookie, API key, user id, email, phone-like 값이 scrub됐는지 확인합니다.
4. 같은 query family에서 반복 성공 또는 Quality Lab 승인이 있는지 확인합니다.
5. Target 또는 plan path가 안정적인지 확인합니다.
6. 최근 failure ratio가 허용 범위인지 확인합니다.
7. Boost가 low-weight이고 traceable한지 확인합니다.

## Troubleshooting

| 증상 | 확인할 것 | 보완 |
| --- | --- | --- |
| suggestion이 생성되지 않음 | record `success`, `selected_target`, `plan_tools` | 성공 plan/execute 후 record 생성 |
| duplicate suggestion이 빠르게 늘어남 | suggestion `id`와 merge policy | `merge_learning_suggestions()` 사용 |
| promoted boost가 적용되지 않음 | query fingerprint와 status | query normalization과 `status=promoted` 확인 |
| shadow는 개선되는데 production은 그대로임 | active mode | 승인된 collection만 promoted mode로 전환 |
| 민감값이 보임 | scrub test와 evidence payload | suggestion 거절 후 scrubbing 수정 |

## 검증

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/ -q -k "learning or target_selector"
```

문서만 수정한 경우:

```bash
cd website
npm run typecheck
npm run build
```

## 관련 문서

- [Trace Learning Loop](../concepts/trace-learning.md)
- [Scrubbing](./scrubbing.md)
- [Shadow And Promotion](./shadow-promotion.md)
- [Target Selection](../search/target-selection.md)
- [Evidence Output](../search/evidence-output.md)
