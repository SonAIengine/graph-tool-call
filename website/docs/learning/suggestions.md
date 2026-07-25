---
title: Suggestions
description: Convert scrubbed execution traces into collection-scoped learning suggestions.
---

# Suggestions

Learning suggestions are proposed graph/search improvements derived from
successful execution traces. They are collection-scoped and safe by default:
new suggestions start as `suggested` or `promotable`, not automatically as
production ranking truth.

## Suggestion Types

| Type | Meaning |
| --- | --- |
| `target_preference` | This query family repeatedly selected a target successfully |
| `plan_path` | This ordered tool path completed successfully |
| `data_flow_edge` | A run observed useful data flowing between two tools |
| `field_mapping` | A field mapping candidate was observed |
| `context_default_candidate` | A stable context default candidate was observed |
| `enum_mapping_candidate` | A value-label enum mapping candidate was observed |

The first three are generated directly from the current public helpers. The
mapping candidate types are stable suggestion kinds that adapters can use when
they derive additional evidence.

## Build A Learning Record

```python
from graph_tool_call.learning import build_trace_learning_record

record = build_trace_learning_record(
    query="find refund-ready orders",
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

The returned record includes `query_family`, `query_fingerprint`, a hashed
session id, scrubbed selector data, and scrubbed trace edges.

## Derive Suggestions

```python
from graph_tool_call.learning import derive_learning_suggestions

suggestions = derive_learning_suggestions(
    record,
    history=previous_attempts,
    existing_suggestions=current_suggestions,
)
```

`derive_learning_suggestions()` returns only the suggestions created or updated
from the input record. Use `merge_learning_suggestions()` when an adapter wants
to maintain a full suggestion list explicitly.

## Suggestion Status

| Status | Meaning |
| --- | --- |
| `suggested` | Observed, but not ready to affect ranking |
| `promotable` | Repeated success or policy gate says it may be promoted |
| `promoted` | Operator or policy has allowed it to affect retrieval/selector |
| `rejected` | Operator or policy decided not to use it |

The default promotion policy requires at least two matching successes and a
recent failure ratio no higher than `0.5`.

## Apply Learning Signals

```python
from graph_tool_call.learning import apply_learning_suggestions

result = apply_learning_suggestions(
    query="find refund-ready orders",
    candidates=[
        {"name": "getOrderDetail", "score": 0.72},
        {"name": "getRefundableOrders", "score": 0.71},
    ],
    suggestions=suggestions,
    mode="promoted",
)
```

Learning boosts are intentionally low-weight and traceable. A suggestion should
help a close candidate move up, not overpower strong semantic or contract
evidence.

## Product UI Guidance

Show operators:

- query family
- suggestion type
- target or plan path
- observation count
- prior failure count
- current status
- evidence source
- promote/reject controls

## Related Pages

- [Scrubbing](./scrubbing.md)
- [Shadow And Promotion](./shadow-promotion.md)
- [Evidence Output](../search/evidence-output.md)
