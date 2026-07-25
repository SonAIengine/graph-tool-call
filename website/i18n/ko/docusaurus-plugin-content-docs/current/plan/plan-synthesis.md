---
title: Plan 합성
description: 선택된 target과 contract evidence로 실행 가능한 tool path를 만듭니다.
---

# Plan 합성

Plan synthesis는 선택된 target을 실행 가능한 path로 바꿉니다. 어떤 input이
context에서 올 수 있는지, 어떤 field를 사용자에게 물어야 하는지, 어떤 producer
tool이 target 전에 필요한지 판단합니다.

## Public API

```python
from graph_tool_call.plan import PathSynthesizer

synthesizer = PathSynthesizer(graph)
plan = synthesizer.synthesize(target_tool="getOrderDetail")
```

## Plan Metadata

Plan은 아래 정보를 보존해야 합니다.

- selected target
- selected producers
- required fields
- user input slots
- enum and dynamic option requirements
- candidate signals
- synthesis diagnostics

## Failure Reasons

- `unknown_target`
- `unsatisfied_field`
- `enum_required`
- `dynamic_option_required`
- `cycle`
- `max_depth`
- `user_input_fallback`

## 관련 문서

- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
