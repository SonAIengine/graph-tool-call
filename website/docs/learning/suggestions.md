---
title: Suggestions
description: Convert scrubbed execution traces into collection-scoped learning suggestions.
---

# Suggestions

Learning suggestions are proposed graph/search improvements derived from
validated traces.

## Suggestion Types

- `target_preference`
- `plan_path`
- `data_flow_edge`
- `field_mapping`
- `context_default_candidate`
- `enum_mapping_candidate`

## Public API

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
)

record = build_trace_learning_record(...)
suggestions = derive_learning_suggestions([record])
```

## Related Pages

- [Scrubbing](./scrubbing.md)
- [Shadow And Promotion](./shadow-promotion.md)
