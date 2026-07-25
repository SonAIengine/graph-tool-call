---
title: User Input Slots
description: default, context, producer tool로 채울 수 없는 field를 구조화합니다.
---

# User Input Slots

User input slot은 누락된 값을 구조화해서 요청하는 방식입니다. product UI는 실행을
멈추고 사용자에게 field를 물은 뒤 추측 없이 resume할 수 있습니다.

## Slot Sources

- required request field
- mapping이 없는 enum field
- dynamic option field
- default가 없는 context field
- ambiguous producer output

## Adapter Role

엔진은 slot을 emit합니다. form, popup, default value, resume UX는 product adapter가
결정합니다.

## 관련 문서

- [Plan Synthesis](./plan-synthesis.md)
- [Failure Taxonomy](./failure-taxonomy.md)
