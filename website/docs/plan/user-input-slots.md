---
title: User Input Slots
description: Represent fields that cannot be filled from defaults, context, or producer tools.
---

# User Input Slots

User input slots are structured requests for missing values. They let a product
pause execution, ask the user or operator for a value, and resume without
guessing.

Slots are part of plan diagnostics, not UI implementation. The engine describes
what is missing; the adapter decides how to ask.

## Slot Sources

| Source | Example |
| --- | --- |
| Required request field | `orderNo` is required and not provided |
| Enum field without mapping | `statusCode` must be one of known enum values |
| Dynamic option field | User must choose an item from an API-produced list |
| Context field without default | `siteNo` is classified as context but no default exists |
| Ambiguous producer output | Multiple producer fields could satisfy the target |

## Slot Shape

A slot should contain enough information for a UI to render a field and for an
adapter to resume execution.

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

## Resume Flow

1. Plan synthesis emits user input slots.
2. Product UI shows a form, popup, or option picker.
3. User selection is stored as resume input.
4. Adapter calls synthesis again with the new `entities`.
5. Runner executes the completed plan.

## Dynamic Options

Some fields should not be guessed from text. For example, a product id or item
code may need a query-specific option list. In that case the synthesizer can
raise `dynamic_option_required` with a producer tool and response path hint.

The adapter can call the producer, show options, then resume with the selected
value.

## UI Guidance

Show:

- field label
- required/optional state
- enum values or option source
- reason code
- example tool that needs the field
- whether a context default exists

Avoid:

- silently filling identifier fields from descriptive Korean text
- turning every missing value into a free-text input when enum/options exist
- storing raw sensitive values in plan metadata

## Related Pages

- [Plan Synthesis](./plan-synthesis.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Quality Lab](../validation/quality-lab.md)
