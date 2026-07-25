---
title: 학습 제안
description: scrub된 execution trace를 collection-scoped learning suggestion으로 변환합니다.
---

# 학습 제안

Learning suggestion은 성공 execution trace에서 도출한 graph/search 개선 후보입니다.
collection 단위로 저장되며 기본적으로 안전합니다. 새 suggestion은 production ranking
truth가 아니라 `suggested` 또는 `promotable` 상태로 시작합니다.

## Suggestion Types

| Type | 의미 |
| --- | --- |
| `target_preference` | 이 query family에서 특정 target이 반복적으로 성공함 |
| `plan_path` | 이 tool path 순서가 성공적으로 완료됨 |
| `data_flow_edge` | run 중 두 tool 사이의 useful data flow가 관찰됨 |
| `field_mapping` | field mapping 후보가 관찰됨 |
| `context_default_candidate` | stable context default 후보가 관찰됨 |
| `enum_mapping_candidate` | value-label enum mapping 후보가 관찰됨 |

앞의 세 가지는 현재 public helper에서 직접 생성됩니다. mapping candidate type은
adapter가 추가 evidence를 도출할 때 사용할 수 있는 안정 suggestion kind입니다.

## Learning Record 만들기

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
    target_selector={"overrode_llm": True, "reason_codes": ["shape_match"]},
    trace_edges=[
        {
            "source": "searchOrders",
            "target": "getRefundableOrders",
            "data_flow": {"to_field": "orderNo"},
        }
    ],
)
```

반환 record에는 `query_family`, `query_fingerprint`, hashed session id, scrub된
selector data, scrub된 trace edge가 포함됩니다.

## Suggestion 도출

```python
from graph_tool_call.learning import derive_learning_suggestions

suggestions = derive_learning_suggestions(
    record,
    history=previous_attempts,
    existing_suggestions=current_suggestions,
)
```

`derive_learning_suggestions()`는 입력 record에서 생성 또는 갱신된 suggestion만
반환합니다. adapter가 전체 suggestion list를 직접 관리할 때는
`merge_learning_suggestions()`를 사용합니다.

## Suggestion Status

| Status | 의미 |
| --- | --- |
| `suggested` | 관찰됐지만 ranking에 영향을 줄 준비는 안 됨 |
| `promotable` | 반복 성공 또는 policy gate로 승격 가능 |
| `promoted` | operator 또는 policy가 retrieval/selector 반영을 허용 |
| `rejected` | operator 또는 policy가 사용하지 않기로 결정 |

기본 promotion policy는 matching success 2회 이상과 최근 failure ratio `0.5` 이하를
요구합니다.

## Learning Signal 적용

```python
from graph_tool_call.learning import apply_learning_suggestions

result = apply_learning_suggestions(
    query="환불 가능한 주문을 찾아줘",
    candidates=[
        {"name": "getOrderDetail", "score": 0.72},
        {"name": "getRefundableOrders", "score": 0.71},
    ],
    suggestions=suggestions,
    mode="promoted",
)
```

Learning boost는 낮은 가중치이며 traceable해야 합니다. suggestion은 근접한 후보를
조금 올리는 용도이지, 강한 semantic/contract evidence를 압도하는 용도가 아닙니다.

## Product UI Guidance

운영자에게 보여줄 항목:

- query family
- suggestion type
- target 또는 plan path
- observation count
- prior failure count
- 현재 status
- evidence source
- promote/reject control

## 관련 문서

- [Scrubbing](./scrubbing.md)
- [Shadow And Promotion](./shadow-promotion.md)
- [Evidence Output](../search/evidence-output.md)
