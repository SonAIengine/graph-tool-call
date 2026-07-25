---
title: Event Schemas
description: Stable event fields emitted by plan and runner flows.
---

# Event Schemas

Event schemas let adapters forward engine progress to logs, SSE, UI panels, and
learning records.

## Common Fields

| Field | Meaning |
| --- | --- |
| `type` | Event type |
| `stage` | Current stage |
| `plan_id` | Plan identifier |
| `step_id` | Step identifier |
| `tool` | Tool name |
| `graph_tool_call_version` | Engine version |
| `trace_metadata` | Adapter-provided trace data |

## Related Pages

- [Runner Events](../plan/runner-events.md)
- [Trace Learning](../concepts/trace-learning.md)
