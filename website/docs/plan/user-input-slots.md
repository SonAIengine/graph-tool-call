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

Keep slot identifiers stable across retries when possible. A product UI can then
store user choices against `field_name`, `tool`, and `reason` without relying on
the wording of `message`.

## Resume Flow

1. Plan synthesis emits user input slots.
2. Product UI shows a form, popup, or option picker.
3. User selection is stored as resume input.
4. Adapter calls synthesis again with the new `entities`.
5. Runner executes the completed plan.

The resume payload should be explicit about where the value came from.

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

Do not store raw session tokens, cookies, or personally identifying values in
slot metadata. If a value is sensitive, store only the fact that the adapter can
resolve it at execution time.

## Dynamic Options

Some fields should not be guessed from text. For example, a product id or item
code may need a query-specific option list. In that case the synthesizer can
raise `dynamic_option_required` with a producer tool and response path hint.

The adapter can call the producer, show options, then resume with the selected
value.

For large option lists, the UI should show a filtered subset and keep the
producer evidence. The plan should remember the chosen identifier, while the UI
can display the human-readable label.

## Reason Codes

| Reason | Meaning | Typical UI |
| --- | --- | --- |
| `unsatisfied_field` | no default, entity, or producer can fill the field | text input or context mapping |
| `enum_required` | the field must be one of known enum values | select box |
| `dynamic_option_required` | options must come from another API call | popup or searchable picker |
| `user_input_fallback` | the engine cannot safely infer the value | explicit confirmation |

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
