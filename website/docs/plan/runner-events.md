---
title: Runner Events
description: Stream structured execution events from PlanRunner to product adapters.
---

# Runner Events

`PlanRunner.run_stream()` emits structured events as a plan executes. Adapters
can forward those events to logs, SSE, UI panels, Quality Lab results, and trace
learning records.

The runner does not know how to call your API. It receives a `call_tool`
function from the adapter.

## Minimal Usage

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

def call_tool(tool_name: str, args: dict):
    return executor.execute(tool_name, args)

runner = PlanRunner(call_tool)

for event in runner.run_stream(
    plan,
    trace_metadata={"collection_id": "orders", "case_id": "order-detail-001"},
):
    send_sse(asdict(event))
```

## Event Lifecycle

```text
plan.started
  step.started
  step.completed
  ...
plan.completed
```

On failure:

```text
plan.started
  step.started
  step.failed
plan.aborted
```

Retry and recovery modes may also emit `step.retrying`, `step.skipped`,
`binding.repaired`, `args.coerced`, or `plan.repaired`.

## Common Fields

| Field | Meaning |
| --- | --- |
| `type` | Stable event type |
| `stage` | Usually `runner` |
| `plan_id` | Current plan id |
| `step_id` | Current step id when applicable |
| `tool` | Tool name when applicable |
| `graph_tool_call_version` | Engine version |
| `trace_metadata` | Adapter-provided safe metadata |

## Trace Metadata

Use `trace_metadata` for safe product context:

```python
trace_metadata = {
    "collection_id": "orders",
    "quality_case_id": "case-001",
    "auth_readiness": {"required": True, "failure_reason": None},
}
```

Do not include token values, cookies, raw user ids, or full request/response
payloads.

## Persisting Events

For long-term storage, keep:

- event type
- plan id and step id
- tool name
- duration
- failure reason
- scrubbed output preview
- trace metadata

Avoid storing full output bodies unless a separate secured audit system owns
that data.

## Related Pages

- [Event Schemas](../reference/event-schemas.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
