---
title: Runner Events
description: Stream structured execution events from PlanRunner to product adapters.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Runner Events

`PlanRunner.run_stream()` turns a `Plan` into a stream of dataclass events. The
runner is intentionally transport-neutral: it does not know about HTTP,
sessions, retries in your gateway, SSE, database rows, or UI state. The product
adapter provides a `call_tool(tool_name, args)` function and decides where each
event should go.

Use runner events when you need the execution path to be observable:

- UI progress for a running plan
- logs that can explain which step failed
- Quality Lab results with per-stage latency
- trace-learning records that can be scrubbed and promoted later
- structured failure responses instead of uncaught executor errors

## Minimal Usage

<Tabs>
  <TabItem value="stream" label="Stream" default>

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

def call_tool(tool_name: str, args: dict):
    return executor.execute(tool_name, args)

runner = PlanRunner(call_tool)

for event in runner.run_stream(
    plan,
    input_context={"siteNo": "10001"},
    trace_metadata={"collection_id": "orders", "case_id": "order-detail-001"},
):
    send_sse(asdict(event))
```

  </TabItem>
  <TabItem value="retry" label="Retry">

```python
from graph_tool_call.plan import PlanRunner, RetryPolicy

runner = PlanRunner(
    call_tool,
    on_error="retry",
    retry_policy=RetryPolicy(max_attempts=3, backoff_base_ms=200),
)

events = list(runner.run_stream(plan))
```

  </TabItem>
  <TabItem value="coerce" label="Coerce args">

```python
from graph_tool_call.plan import PlanRunner

runner = PlanRunner(
    call_tool,
    tools=tool_schemas_by_name,
    validate_args="coerce",
)

for event in runner.run_stream(plan):
    if event.type == "args.coerced":
        audit(event.changes)
```

  </TabItem>
</Tabs>

`input_context` supplies values for both `${input.foo}` and
`${user_input.foo}` bindings. `trace_metadata` is copied onto every emitted
event, so keep it compact and scrubbed.

## Event Lifecycle

The default runner mode is linear and aborts on the first hard failure.

```text
plan.started
  step.started
  step.completed
  step.started
  step.completed
plan.completed
```

When a binding or tool call fails in `on_error="abort"` mode:

```text
plan.started
  step.started
  step.failed
plan.aborted
```

Recovery modes add events without changing the base contract:

| Event | Emitted When | What The Adapter Should Do |
| --- | --- | --- |
| `step.retrying` | a retryable step failed and another attempt will run | show retry state, keep the run open |
| `step.skipped` | `recover` mode skipped an unconsumed failed step | show degraded progress, keep the run open |
| `plan.repaired` | a repairer created a replacement plan | replace the visible plan id/path if needed |
| `binding.repaired` | stale `${sN.path}` binding was redirected | store as low-confidence repair evidence |
| `args.coerced` | args were type-cast or enum-folded before execution | expose the coercion in diagnostics |

The v1 runner does not perform fan-out, conditionals, or automatic replanning
unless `on_error="recover"` is configured with a `PlanRepairer`.

## Event Types

| Type | Main Fields | Success Path |
| --- | --- | --- |
| `plan.started` | `plan_id`, `goal`, `step_count` | first event |
| `step.started` | `step_id`, `tool`, `args_resolved`, `index`, `total` | before each tool call |
| `step.completed` | `duration_ms`, `output_preview`, `output_size` | after a successful tool call |
| `plan.completed` | `output`, `total_duration_ms`, `trace_steps` | final success event |
| `step.failed` | `error`, `duration_ms` | failed step before abort |
| `plan.aborted` | `failed_step`, `error`, `trace_steps` | final failure event |

Every event can carry:

| Field | Meaning |
| --- | --- |
| `type` | stable event type for routing |
| `stage` | currently `runner` |
| `plan_id` | current plan id |
| `step_id` | current step id when applicable |
| `tool` | tool name when applicable |
| `graph_tool_call_version` | engine version |
| `trace_metadata` | adapter-provided safe metadata |

## Payload Examples

<Tabs>
  <TabItem value="started" label="Step started" default>

```json
{
  "type": "step.started",
  "stage": "runner",
  "plan_id": "plan-42",
  "step_id": "s1",
  "tool": "getOrderDetail",
  "args_resolved": {"orderNo": "ORD-1001"},
  "index": 1,
  "total": 2,
  "graph_tool_call_version": "0.31.0",
  "trace_metadata": {"collection_id": "orders-api", "quality_case_id": "case-001"}
}
```

  </TabItem>
  <TabItem value="completed" label="Step completed">

```json
{
  "type": "step.completed",
  "stage": "runner",
  "plan_id": "plan-42",
  "step_id": "s1",
  "tool": "getOrderDetail",
  "duration_ms": 184,
  "output_preview": {"orderNo": "ORD-1001", "status": "PAID"},
  "output_size": 91,
  "graph_tool_call_version": "0.31.0",
  "trace_metadata": {"collection_id": "orders-api", "quality_case_id": "case-001"}
}
```

  </TabItem>
  <TabItem value="aborted" label="Plan aborted">

```json
{
  "type": "plan.aborted",
  "stage": "runner",
  "plan_id": "plan-42",
  "failed_step": "s2",
  "error": {
    "kind": "tool",
    "message": "HTTP 403",
    "exception_type": "PermissionError"
  },
  "total_duration_ms": 412,
  "trace_steps": [],
  "graph_tool_call_version": "0.31.0",
  "trace_metadata": {
    "collection_id": "orders-api",
    "auth_readiness": {"required": true, "failure_reason": "auth_failed"}
  }
}
```

  </TabItem>
</Tabs>

## Adapter Contract

The adapter should keep the runner boundary narrow:

| Runner Input | Adapter Owns |
| --- | --- |
| `Plan` | retrieving or synthesizing the plan |
| `input_context` | user-entered fields, extracted entities, collection defaults |
| `trace_metadata` | collection id, case id, safe auth readiness, request id |
| `call_tool` | HTTP execution, auth headers, host allowlists, mutation policy |

Do not put raw tokens, cookies, emails, phone numbers, raw user ids, or full
request/response bodies in `trace_metadata`. If a product needs audit-grade
payload storage, keep that in a separate secured system and store only a
reference id in runner events.

## SSE And UI Mapping

For product UIs, forward events as a stable envelope:

```json
{
  "type": "runner.event",
  "run_id": "ql-run-20260725-001",
  "event": {"type": "step.completed", "step_id": "s1"}
}
```

Recommended UI grouping:

| UI State | Event Condition |
| --- | --- |
| Running | `plan.started`, `step.started`, `step.retrying` |
| Partial progress | `step.completed`, `step.skipped`, `args.coerced` |
| Needs attention | `binding.repaired`, `plan.repaired` |
| Success | `plan.completed` |
| Failed | `step.failed`, `plan.aborted` |

## Persisting Events

For long-term storage, keep the fields that explain behavior without exposing
payloads:

- event type
- plan id and step id
- tool name
- duration
- failure reason
- retry or repair state
- scrubbed output preview
- trace metadata

Quality Lab and trace learning should use the same event stream, then derive a
compact record from it. This keeps debugging, evaluation, and learning grounded
in one source of truth.

## Troubleshooting

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| `plan.aborted` with `kind=binding` | a required producer value is missing | inspect `PlanStep.args` bindings and upstream `output_preview` |
| `step.failed` with `kind=tool` | adapter executor raised | inspect HTTP status, auth readiness, and executor logs |
| no `step.completed` events | first step failed before output | check `step.failed.error` and `failed_step` |
| `args.coerced` missing | `validate_args` is `off` or `tools` map is absent | configure `PlanRunner(..., tools=..., validate_args="coerce")` |
| retries never happen | step is not retryable or no `RetryPolicy` is configured | set `PlanStep.retryable=True` or `RetryPolicy(retry_all=True)` |

## Related Pages

- [Event Schemas](../reference/event-schemas.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Plan Synthesis](./plan-synthesis.md)
- [Trace Learning](../concepts/trace-learning.md)
