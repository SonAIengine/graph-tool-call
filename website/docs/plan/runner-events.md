---
title: Runner Events
description: Stream structured execution events from PlanRunner to product adapters.
---

# Runner Events

`PlanRunner.run_stream()` emits structured events so adapters can forward
progress to logs, SSE, or user interfaces.

## Event Shape

Events may include:

| Field | Meaning |
| --- | --- |
| `type` | Event type |
| `stage` | `intent`, `plan`, `step`, `response`, or `failure` stage |
| `plan_id` | Current plan id |
| `step_id` | Current step id when applicable |
| `tool` | Tool being executed |
| `graph_tool_call_version` | Engine version |
| `trace_metadata` | Adapter-provided trace metadata |

## Usage

```python
from graph_tool_call.plan import PlanRunner

runner = PlanRunner(execute_tool=execute_tool)

async for event in runner.run_stream(plan, trace_metadata={"collection_id": cid}):
    print(event)
```

## Related Pages

- [Failure Taxonomy](./failure-taxonomy.md)
- [Trace Learning](../concepts/trace-learning.md)
