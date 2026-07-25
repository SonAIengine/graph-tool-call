---
title: Response Synthesis
description: Generate structured success and failure responses after tool execution.
---

# Response Synthesis

Response synthesis converts plan and runner output into a final assistant-facing
answer. It should preserve failure reasons and evidence rather than hiding them.

## Public Helpers

```python
from graph_tool_call.plan import (
    synthesize_failure_response,
    synthesize_success_response,
)
```

## Guidance

- Keep raw API payload handling in the adapter.
- Keep final response generation aware of stage, failed step, and reason code.
- Preserve `plan_id` and trace metadata for debugging.

## Related Pages

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
