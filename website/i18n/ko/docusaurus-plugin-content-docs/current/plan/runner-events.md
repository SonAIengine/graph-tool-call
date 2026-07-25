---
title: Runner 이벤트
description: PlanRunner에서 product adapter로 structured execution event를 stream합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Runner 이벤트

`PlanRunner.run_stream()`은 `Plan`을 dataclass event stream으로 바꿉니다.
Runner는 의도적으로 transport-neutral합니다. HTTP, session, gateway retry,
SSE, DB row, UI state를 알지 않고, product adapter가
`call_tool(tool_name, args)` 함수를 제공한 뒤 각 event를 어디로 보낼지
결정합니다.

Runner event는 실행 경로를 관측 가능하게 만들어야 할 때 사용합니다.

- 실행 중인 plan의 UI progress
- 어떤 step에서 실패했는지 설명하는 log
- stage별 latency가 있는 Quality Lab 결과
- 이후 scrub/promotion 가능한 trace learning record
- executor error를 숨기지 않는 structured failure response

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

`input_context`는 `${input.foo}`와 `${user_input.foo}` binding 모두에 값을
공급합니다. `trace_metadata`는 모든 event에 복사되므로 작고 scrub된 값만
넣습니다.

## Event Lifecycle

기본 runner mode는 linear execution이며 첫 hard failure에서 abort합니다.

```text
plan.started
  step.started
  step.completed
  step.started
  step.completed
plan.completed
```

`on_error="abort"` mode에서 binding 또는 tool call이 실패하면 다음 흐름입니다.

```text
plan.started
  step.started
  step.failed
plan.aborted
```

Recovery mode는 기존 contract를 깨지 않고 event를 추가합니다.

| Event | 언제 발생하나 | Adapter가 할 일 |
| --- | --- | --- |
| `step.retrying` | retry 가능한 step이 실패했고 다음 attempt가 실행될 때 | retry 상태를 표시하고 run을 유지 |
| `step.skipped` | `recover` mode가 소비되지 않는 실패 step을 skip할 때 | degraded progress로 표시하고 run을 유지 |
| `plan.repaired` | repairer가 대체 plan을 만들 때 | 필요하면 화면의 plan id/path 갱신 |
| `binding.repaired` | 오래된 `${sN.path}` binding이 다른 path로 복구될 때 | 낮은 confidence의 repair evidence로 저장 |
| `args.coerced` | 실행 전 type cast 또는 enum folding이 발생할 때 | coercion을 diagnostics에 노출 |

v1 runner는 `on_error="recover"`와 `PlanRepairer`를 설정한 경우를 제외하면
fan-out, conditional, automatic replanning을 수행하지 않습니다.

## Event Types

| Type | 주요 field | Success path |
| --- | --- | --- |
| `plan.started` | `plan_id`, `goal`, `step_count` | 첫 event |
| `step.started` | `step_id`, `tool`, `args_resolved`, `index`, `total` | 각 tool call 직전 |
| `step.completed` | `duration_ms`, `output_preview`, `output_size` | tool call 성공 후 |
| `plan.completed` | `output`, `total_duration_ms`, `trace_steps` | 최종 성공 event |
| `step.failed` | `error`, `duration_ms` | abort 전 실패 step |
| `plan.aborted` | `failed_step`, `error`, `trace_steps` | 최종 실패 event |

모든 event는 아래 field를 가질 수 있습니다.

| Field | 의미 |
| --- | --- |
| `type` | routing에 쓰는 stable event type |
| `stage` | 현재는 `runner` |
| `plan_id` | 현재 plan id |
| `step_id` | 해당될 때 현재 step id |
| `tool` | 해당될 때 tool name |
| `graph_tool_call_version` | engine version |
| `trace_metadata` | adapter가 제공한 safe metadata |

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

Adapter는 runner 경계를 좁게 유지해야 합니다.

| Runner 입력 | Adapter 책임 |
| --- | --- |
| `Plan` | plan retrieval 또는 synthesis |
| `input_context` | 사용자 입력 field, 추출 entity, collection default |
| `trace_metadata` | collection id, case id, safe auth readiness, request id |
| `call_tool` | HTTP 실행, auth header, host allowlist, mutation policy |

raw token, cookie, email, phone number, raw user id, full request/response body는
`trace_metadata`에 넣지 않습니다. 제품에서 audit-grade payload 저장이 필요하면
별도 보안 system에 두고 runner event에는 reference id만 남깁니다.

## SSE And UI Mapping

제품 UI에는 안정적인 envelope으로 event를 forwarding하는 편이 좋습니다.

```json
{
  "type": "runner.event",
  "run_id": "ql-run-20260725-001",
  "event": {"type": "step.completed", "step_id": "s1"}
}
```

권장 UI grouping은 다음입니다.

| UI State | Event Condition |
| --- | --- |
| Running | `plan.started`, `step.started`, `step.retrying` |
| Partial progress | `step.completed`, `step.skipped`, `args.coerced` |
| Needs attention | `binding.repaired`, `plan.repaired` |
| Success | `plan.completed` |
| Failed | `step.failed`, `plan.aborted` |

## Persisting Events

장기 저장에는 payload 없이 동작을 설명할 수 있는 field만 남깁니다.

- event type
- plan id와 step id
- tool name
- duration
- failure reason
- retry 또는 repair state
- scrub된 output preview
- trace metadata

Quality Lab과 trace learning은 같은 event stream을 사용하고, 거기서 compact record를
derive해야 합니다. 그래야 debugging, evaluation, learning이 하나의 source of truth에
묶입니다.

## Troubleshooting

| 증상 | 가능한 원인 | 확인할 것 |
| --- | --- | --- |
| `plan.aborted`와 `kind=binding` | 필요한 producer 값이 없음 | `PlanStep.args` binding과 upstream `output_preview` |
| `step.failed`와 `kind=tool` | adapter executor가 예외를 던짐 | HTTP status, auth readiness, executor log |
| `step.completed`가 없음 | 첫 step이 output 전에 실패함 | `step.failed.error`와 `failed_step` |
| `args.coerced`가 없음 | `validate_args`가 `off`이거나 `tools` map이 없음 | `PlanRunner(..., tools=..., validate_args="coerce")` 설정 |
| retry가 발생하지 않음 | step이 retryable이 아니거나 `RetryPolicy`가 없음 | `PlanStep.retryable=True` 또는 `RetryPolicy(retry_all=True)` |

## 관련 문서

- [Event Schemas](../reference/event-schemas.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Plan Synthesis](./plan-synthesis.md)
- [Trace Learning](../concepts/trace-learning.md)
