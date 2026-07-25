---
title: 사용자 입력 슬롯
description: default, context, producer tool로 채울 수 없는 field를 구조화합니다.
---

# 사용자 입력 슬롯

User input slot은 누락된 값을 구조화해서 요청하는 방식입니다. product UI는 실행을
멈추고 사용자에게 field를 물은 뒤 추측 없이 resume할 수 있습니다.

Slot은 plan diagnostic의 일부이지 UI 구현체가 아닙니다. 엔진은 무엇이 부족한지
설명하고, adapter가 어떻게 질문할지 결정합니다.

## Slot Sources

| Source | 예시 |
| --- | --- |
| Required request field | `orderNo`가 필수인데 제공되지 않음 |
| Enum field without mapping | `statusCode`가 알려진 enum 중 하나여야 함 |
| Dynamic option field | API-produced list에서 사용자가 항목을 골라야 함 |
| Context field without default | `siteNo`가 context로 분류됐지만 default가 없음 |
| Ambiguous producer output | 여러 producer field가 target을 채울 수 있음 |

## Slot Shape

Slot은 UI가 field를 렌더링하고 adapter가 resume할 수 있을 만큼의 정보를 가져야
합니다.

```json
{
  "field_name": "statusCode",
  "semantic_tag": "order.status",
  "kind": "data",
  "required": true,
  "tool": "getOrderList",
  "reason": "enum_required",
  "enum": ["READY", "CANCELLED"],
  "message": "Choose an order status."
}
```

가능하면 retry 사이에서도 slot 식별자를 안정적으로 유지합니다. 그러면 product UI가
`message` 문구에 의존하지 않고 `field_name`, `tool`, `reason` 기준으로 사용자
선택값을 저장할 수 있습니다.

## Resume Flow

1. Plan synthesis가 user input slot을 emit합니다.
2. Product UI가 form, popup, option picker를 보여줍니다.
3. 사용자 선택값이 resume input으로 저장됩니다.
4. Adapter가 새 `entities`로 synthesis를 다시 호출합니다.
5. Runner가 완성된 plan을 실행합니다.

resume payload는 값의 출처를 명시하는 편이 좋습니다.

```json
{
  "entities": {
    "statusCode": "READY"
  },
  "resume_metadata": {
    "source": "user_input_slot",
    "slot_reason": "enum_required",
    "confirmed_by_user": true
  }
}
```

slot metadata에는 raw session token, cookie, 개인 식별값을 저장하지 않습니다.
민감한 값이라면 adapter가 실행 시점에 resolve할 수 있다는 사실만 남깁니다.

## Dynamic Options

어떤 field는 text에서 추측하면 안 됩니다. 예를 들어 product id나 item code는 query별
option list가 필요할 수 있습니다. 이때 synthesizer는 producer tool과 response path
hint가 포함된 `dynamic_option_required`를 낼 수 있습니다.

Adapter는 producer를 호출하고 option을 보여준 뒤, 선택된 값으로 resume합니다.

option list가 크면 UI는 필터링된 subset을 보여주고 producer evidence를 보존해야
합니다. plan에는 선택된 identifier를 기억하고, UI는 사람이 읽을 label을 표시할 수
있습니다.

## Reason code

| Reason | 의미 | 일반적인 UI |
| --- | --- | --- |
| `unsatisfied_field` | default, entity, producer로 채울 수 없음 | text input 또는 context mapping |
| `enum_required` | 알려진 enum 중 하나여야 함 | select box |
| `dynamic_option_required` | 다른 API call로 option을 받아야 함 | popup 또는 searchable picker |
| `user_input_fallback` | engine이 안전하게 추론할 수 없음 | 명시적 확인 |

## UI Guidance

보여줄 항목:

- field label
- required/optional 상태
- enum values 또는 option source
- reason code
- 이 field가 필요한 example tool
- context default 존재 여부

피할 것:

- 설명형 한국어 text에서 identifier field를 조용히 채우기
- enum/options가 있는데 모든 missing value를 free-text input으로 만들기
- raw sensitive value를 plan metadata에 저장하기

## 관련 문서

- [Plan Synthesis](./plan-synthesis.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Quality Lab](../validation/quality-lab.md)
