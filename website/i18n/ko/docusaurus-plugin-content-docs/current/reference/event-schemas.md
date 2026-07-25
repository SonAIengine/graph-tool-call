---
title: Event Schema
description: plan과 runner flow에서 emit되는 stable event field입니다.
---

# Event Schema

Event schema는 adapter가 engine progress를 log, SSE, UI panel, learning record로
전달할 수 있게 합니다.

## Common Fields

| Field | Meaning |
| --- | --- |
| `type` | event type |
| `stage` | current stage |
| `plan_id` | plan identifier |
| `step_id` | step identifier |
| `tool` | tool name |
| `graph_tool_call_version` | engine version |
| `trace_metadata` | adapter-provided trace data |

## 관련 문서

- [Runner Events](../plan/runner-events.md)
- [Trace Learning](../concepts/trace-learning.md)
