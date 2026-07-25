---
title: Runner Events
description: PlanRunner에서 product adapter로 structured execution event를 stream합니다.
---

# Runner Events

`PlanRunner.run_stream()`은 adapter가 log, SSE, UI에 progress를 전달할 수 있도록
structured event를 emit합니다.

## Event Shape

| Field | Meaning |
| --- | --- |
| `type` | event type |
| `stage` | `intent`, `plan`, `step`, `response`, `failure` stage |
| `plan_id` | current plan id |
| `step_id` | current step id |
| `tool` | 실행 중인 tool |
| `graph_tool_call_version` | engine version |
| `trace_metadata` | adapter-provided trace metadata |

## Usage

```python
from graph_tool_call.plan import PlanRunner

runner = PlanRunner(execute_tool=execute_tool)

async for event in runner.run_stream(plan, trace_metadata={"collection_id": cid}):
    print(event)
```

## 관련 문서

- [Failure Taxonomy](./failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
