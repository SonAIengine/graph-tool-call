---
title: Event Schema
description: plan과 runner flow가 emit하는 안정 event field입니다.
---

# Event Schema

Plan runner event는 engine progress를 log, SSE, Quality Lab result, learning
record로 전달하기 위한 구조화된 payload입니다. Python에서는 dataclass이며
`dataclasses.asdict()`로 직렬화할 수 있습니다.

## 공통 field

| Field | 의미 |
| --- | --- |
| `type` | 안정 event type string |
| `stage` | engine stage, 보통 `runner` |
| `plan_id` | plan id |
| `step_id` | step event일 때 step id |
| `tool` | tool event일 때 tool name |
| `graph_tool_call_version` | event를 emit한 library version |
| `trace_metadata` | adapter가 추가한 safe metadata |

`trace_metadata`에는 collection id, case id, request id, auth readiness 같은
안전한 값만 넣으세요. token이나 cookie 원문은 넣지 않습니다.

## Runner event type

| Type | 시점 | 주요 field |
| --- | --- | --- |
| `plan.started` | run 시작 | `goal`, `step_count` |
| `step.started` | tool 호출 직전 | `args_resolved`, `index`, `total` |
| `step.completed` | step 성공 | `duration_ms`, `output_preview`, `output_size` |
| `step.failed` | step 실패 | `error`, `duration_ms` |
| `plan.completed` | plan 성공 | `output`, `trace_steps`, `total_duration_ms` |
| `plan.aborted` | 실패 후 중단 | `failed_step`, `error`, `trace_steps` |
| `step.retrying` | retry 직전 | `attempt`, `max_attempts`, `delay_ms` |
| `step.skipped` | recover mode에서 skip | `reason`, `error` |
| `plan.repaired` | replacement plan 생성 | `old_plan_id`, `new_plan_id`, `excluded_tools` |
| `binding.repaired` | binding recovery 성공 | `field_name`, `recovered_path` |
| `args.coerced` | argument coercion 발생 | `changes`, `unresolved` |

## Streaming 예시

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

## Error reason

adapter는 실패 reason code를 안정적으로 유지해야 합니다.

| Reason | 의미 |
| --- | --- |
| `auth_context_required` | runtime user/session context 없음 |
| `auth_profile_missing` | auth가 필요한데 collection auth profile 없음 |
| `auth_header_resolution_failed` | execution header 생성 실패 |
| `auth_failed` | downstream API 401/403 |
| `http_4xx` | 기타 client error |
| `http_5xx` | downstream server error |
| `unsatisfied_field` | required input을 채우지 못함 |
| `cleanup_failed` | mutation cleanup 실패 |

## 운영 지침

- event field 이름을 바꾸지 말고 그대로 forwarding합니다.
- 제품별 field는 `trace_metadata`에 추가합니다.
- full sensitive payload 대신 compact preview만 저장합니다.
- learning record는 `plan.completed`와 `plan.aborted`에서 생성합니다.

## 관련 문서

- [Runner 이벤트](../plan/runner-events.md)
- [실패 분류](../plan/failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
