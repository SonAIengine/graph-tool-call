---
title: Plan Synthesis
description: Build executable tool paths from a selected target and contract evidence.
---

# Plan Synthesis

Plan synthesis turns a selected target into an executable path. It decides which
arguments are already known, which fields should come from collection context,
which producer tools can supply missing values, and which values must be asked
from the user.

The synthesizer is deterministic and transport-agnostic. It consumes graph/tool
metadata; it does not call HTTP APIs, read databases, or resolve runtime auth.

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

For each required consume field, the synthesizer checks:

1. user or LLM-extracted `entities`
2. `context_defaults` for ambient context fields
3. producer tools with matching semantic tag
4. producer tools with matching field name
5. workflow or graph edge fallback
6. user input fallback when allowed by the field policy

This order keeps user-provided facts ahead of inferred graph paths.

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

`PlanStep.args` may contain binding expressions such as `${s1.items.0.id}` or
`${input.keyword}`. The runner resolves them against previous step outputs and
runtime inputs.

## Metadata To Preserve

Good adapters store `Plan.metadata.synthesis` with:

| Field | Purpose |
| --- | --- |
| `target` | Final selected target |
| `selected_producers` | Producer tools used to satisfy required fields |
| `candidate_signals` | Why producer candidates were ranked |
| `user_input_slots` | Fields that need user confirmation |
| `context_defaults` | Context keys used, not secret values |
| `enum_field_names` | Enum fields requiring mapping |
| `target_selector` | LLM target, final target, override diagnostics |

## Failure Reasons

`PlanSynthesisError` exposes `to_dict()` so adapters do not need to parse
exception text.

```python
from graph_tool_call.plan import PlanSynthesisError

try:
    plan = synthesizer.synthesize(target="getOrderDetail", entities={})
except PlanSynthesisError as exc:
    print(exc.to_dict())
```

Common reason codes:

| Reason | Meaning |
| --- | --- |
| `unknown_target` | Target tool is not present in the graph |
| `unsatisfied_field` | Required field cannot be filled |
| `enum_required` | Required enum needs user or adapter mapping |
| `dynamic_option_required` | A dynamic option list should be fetched first |
| `cycle` | Producer search revisited a tool already in progress |
| `max_depth` | Producer chain exceeded the configured depth |
| `user_input_fallback` | Plan can continue only after user input |

## Adapter Boundary

The engine emits the plan and diagnostics. The adapter decides:

- how to display user input slots
- how to resume after user selection
- how to resolve auth/session headers
- how to execute each tool
- how to persist plan attempts and failures

## Related Pages

- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Target Selection](../search/target-selection.md)
