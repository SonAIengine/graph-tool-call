---
title: Event Schemas
description: Stable event fields emitted by plan and runner flows.
---

# Event Schemas

Plan runner events let adapters forward engine progress to logs, SSE streams,
Quality Lab results, and learning records. Events are dataclasses in Python and
can be serialized with `dataclasses.asdict()`.

## Common Fields

Every runner event can include these fields:

| Field | Meaning |
| --- | --- |
| `type` | Stable event type string |
| `stage` | Engine stage, usually `runner` |
| `plan_id` | Plan identifier |
| `step_id` | Step identifier when the event belongs to a step |
| `tool` | Tool name when the event belongs to a tool call |
| `graph_tool_call_version` | Library version that emitted the event |
| `trace_metadata` | Adapter-provided metadata copied onto every event |

`trace_metadata` is the right place for safe identifiers such as collection id,
case id, request id, or auth readiness status. Do not put raw tokens or cookies
there.

## Runner Event Types

| Type | Emitted When | Important Fields |
| --- | --- | --- |
| `plan.started` | A run begins | `goal`, `step_count` |
| `step.started` | A step is about to call a tool | `args_resolved`, `index`, `total` |
| `step.completed` | A step returns successfully | `duration_ms`, `output_preview`, `output_size` |
| `step.failed` | A step call or binding fails | `error`, `duration_ms` |
| `plan.completed` | The whole plan succeeds | `output`, `trace_steps`, `total_duration_ms` |
| `plan.aborted` | The run stops after a failure | `failed_step`, `error`, `trace_steps` |
| `step.retrying` | Retry mode is about to retry a step | `attempt`, `max_attempts`, `delay_ms` |
| `step.skipped` | Recover mode skips an unused failed step | `reason`, `error` |
| `plan.repaired` | Recover mode synthesized a replacement plan | `old_plan_id`, `new_plan_id`, `excluded_tools` |
| `binding.repaired` | Binding recovery found an alternate value path | `field_name`, `recovered_path`, `value_preview` |
| `args.coerced` | Argument validation coerced values | `changes`, `unresolved` |

## Streaming Example

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

runner = PlanRunner(call_tool, on_error="abort")

for event in runner.run_stream(
    plan,
    trace_metadata={
        "collection_id": "orders",
        "quality_case_id": "order-detail-001",
    },
):
    send_sse(asdict(event))
```

## Example Event

```json
{
  "type": "step.completed",
  "stage": "runner",
  "plan_id": "plan-001",
  "step_id": "s2",
  "tool": "getOrderDetail",
  "duration_ms": 184,
  "output_preview": {"orderNo": "A-100"},
  "output_size": 472,
  "graph_tool_call_version": "0.32.1",
  "trace_metadata": {
    "collection_id": "orders",
    "quality_case_id": "order-detail-001"
  }
}
```

## Error Shape

`step.failed` and `plan.aborted` carry an `error` object. Adapters should keep
reason codes stable and product-visible.

```json
{
  "type": "step.failed",
  "step_id": "s1",
  "tool": "getOrderDetail",
  "error": {
    "kind": "tool",
    "message": "HTTP 403",
    "reason_code": "auth_failed"
  }
}
```

Recommended adapter reason codes include:

| Reason | Meaning |
| --- | --- |
| `auth_context_required` | Runtime user/session context was missing |
| `auth_profile_missing` | Tool required auth but the collection had no auth profile |
| `auth_header_resolution_failed` | Adapter could not resolve execution headers |
| `auth_failed` | Downstream API returned 401 or 403 |
| `http_4xx` | Downstream API returned another client error |
| `http_5xx` | Downstream API returned a server error |
| `unsatisfied_field` | Required request input could not be filled |
| `cleanup_failed` | Mutation cleanup failed |

## Event Handling Guidelines

- Forward events as-is; avoid renaming fields in product adapters.
- Add product-specific facts under `trace_metadata`.
- Store only compact previews, not full sensitive payloads.
- Use `plan.completed` and `plan.aborted` to create trace learning records.
- Keep event consumers tolerant of additive fields.

## Related Pages

- [Runner Events](../plan/runner-events.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
