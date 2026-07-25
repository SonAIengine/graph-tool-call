---
title: Runner 이벤트
description: PlanRunner에서 product adapter로 structured execution event를 stream합니다.
---

# Runner 이벤트

`PlanRunner.run_stream()`은 adapter가 log, SSE, UI에 progress를 전달할 수 있도록
structured event를 emit합니다. Quality Lab 결과와 trace learning record에도 같은
event를 재사용할 수 있습니다.

Runner는 API 호출 방식을 모릅니다. Adapter가 `call_tool` 함수를 전달합니다.

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

실패 시:

```text
plan.started
  step.started
  step.failed
plan.aborted
```

Retry/recovery mode에서는 `step.retrying`, `step.skipped`, `binding.repaired`,
`args.coerced`, `plan.repaired` 같은 event가 추가될 수 있습니다.

## Common Fields

| Field | Meaning |
| --- | --- |
| `type` | 안정적인 event type |
| `stage` | 보통 `runner` |
| `plan_id` | 현재 plan id |
| `step_id` | 해당될 때 현재 step id |
| `tool` | 해당될 때 tool name |
| `graph_tool_call_version` | engine version |
| `trace_metadata` | adapter가 제공한 safe metadata |

## Trace Metadata

```python
trace_metadata = {
    "collection_id": "orders",
    "quality_case_id": "case-001",
    "auth_readiness": {"required": True, "failure_reason": None},
}
```

token value, cookie, raw user id, full request/response payload는 넣지 않습니다.

## Persisting Events

장기 저장에는 아래 정도만 남깁니다.

- event type
- plan id와 step id
- tool name
- duration
- failure reason
- scrub된 output preview
- trace metadata

full output body는 별도 보안 audit system이 소유하는 경우에만 저장합니다.

## 관련 문서

- [Event Schemas](../reference/event-schemas.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
