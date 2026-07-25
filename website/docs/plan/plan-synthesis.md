---
title: Plan Synthesis
description: Build executable tool paths from a selected target and contract evidence.
---

# Plan Synthesis

Plan synthesis turns a selected target into an executable path. It decides which
inputs can come from context, which fields need user input, and which producer
tools may be needed before the target.

## Public API

```python
from graph_tool_call.plan import PathSynthesizer

synthesizer = PathSynthesizer(graph)
plan = synthesizer.synthesize(target_tool="getOrderDetail")
```

## Plan Metadata

Plans should preserve:

- selected target
- selected producers
- required fields
- user input slots
- enum and dynamic option requirements
- candidate signals
- synthesis diagnostics

## Failure Reasons

Common plan synthesis reasons include:

- `unknown_target`
- `unsatisfied_field`
- `enum_required`
- `dynamic_option_required`
- `cycle`
- `max_depth`
- `user_input_fallback`

## Related Pages

- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
