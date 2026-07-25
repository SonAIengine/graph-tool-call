---
title: Plan 합성
description: 선택된 target과 contract evidence로 실행 가능한 tool path를 만듭니다.
---

# Plan 합성

Plan synthesis는 선택된 target을 실행 가능한 path로 바꿉니다. 이미 알고 있는
argument, collection context에서 채울 field, missing value를 공급할 producer tool,
사용자에게 물어야 할 값을 결정합니다.

Synthesizer는 deterministic하고 transport-agnostic합니다. graph/tool metadata를
소비할 뿐 HTTP API를 호출하거나, DB를 읽거나, runtime auth를 해결하지 않습니다.

## Public API

```python
from graph_tool_call.plan import PathSynthesizer

synthesizer = PathSynthesizer(
    graph_payload,
    context_defaults={"locale": "ko_KR"},
    enum_field_names={"statusCode"},
)

plan = synthesizer.synthesize(
    target="getOrderDetail",
    entities={"orderNo": "A-100"},
    goal="Find order detail",
)
```

## Input Priority

필수 consume field마다 synthesizer는 아래 순서로 값을 찾습니다.

1. 사용자 또는 LLM이 추출한 `entities`
2. ambient context field용 `context_defaults`
3. 같은 semantic tag를 produce하는 tool
4. 같은 field name을 produce하는 tool
5. workflow 또는 graph edge fallback
6. field policy가 허용할 때 user input fallback

이 순서는 사용자가 명시한 사실을 graph inference보다 우선합니다.

## Plan Shape

```python
from graph_tool_call.plan import Plan, PlanStep

plan = Plan(
    id="plan-001",
    goal="Find order detail",
    steps=[
        PlanStep(id="s1", tool="searchOrders", args={"keyword": "A-100"}),
        PlanStep(id="s2", tool="getOrderDetail", args={"orderNo": "${s1.items.0.orderNo}"}),
    ],
    output_binding="${s2}",
    metadata={"synthesis": {"target": "getOrderDetail"}},
)
```

`PlanStep.args`에는 `${s1.items.0.id}` 또는 `${input.keyword}` 같은 binding
expression이 들어갈 수 있습니다. Runner는 이전 step output과 runtime input을 기준으로
binding을 resolve합니다.

## 보존할 Metadata

좋은 adapter는 `Plan.metadata.synthesis`에 아래 정보를 저장합니다.

| Field | 목적 |
| --- | --- |
| `target` | 최종 selected target |
| `selected_producers` | required field를 채우는 데 사용된 producer tool |
| `candidate_signals` | producer candidate가 rank된 이유 |
| `user_input_slots` | 사용자 확인이 필요한 field |
| `context_defaults` | 사용된 context key. secret value는 저장하지 않음 |
| `enum_field_names` | mapping이 필요한 enum field |
| `target_selector` | LLM target, final target, override diagnostic |

## Failure Reasons

`PlanSynthesisError`는 `to_dict()`를 제공합니다. adapter는 exception text를 parsing할
필요가 없습니다.

```python
from graph_tool_call.plan import PlanSynthesisError

try:
    plan = synthesizer.synthesize(target="getOrderDetail", entities={})
except PlanSynthesisError as exc:
    print(exc.to_dict())
```

대표 reason code:

| Reason | 의미 |
| --- | --- |
| `unknown_target` | target tool이 graph에 없음 |
| `unsatisfied_field` | required field를 채울 수 없음 |
| `enum_required` | required enum에 사용자 또는 adapter mapping 필요 |
| `dynamic_option_required` | dynamic option list를 먼저 가져와야 함 |
| `cycle` | producer search가 이미 처리 중인 tool을 다시 방문함 |
| `max_depth` | producer chain이 configured depth를 초과함 |
| `user_input_fallback` | 사용자 입력 이후에만 plan 진행 가능 |

## Adapter Boundary

엔진은 plan과 diagnostics를 emit합니다. Adapter가 결정할 내용은 아래입니다.

- user input slot을 어떻게 보여줄지
- 사용자 선택 이후 어떻게 resume할지
- auth/session header를 어떻게 resolve할지
- 각 tool을 어떻게 execute할지
- plan attempt와 failure를 어디에 저장할지

## 관련 문서

- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Target Selection](../search/target-selection.md)
