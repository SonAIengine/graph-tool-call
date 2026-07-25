---
title: Middleware
description: Use middleware to filter model tool catalogs before invocation.
---

# Middleware

Middleware integrations intercept the tool catalog before a model invocation and
replace a large raw catalog with a compact graph-tool-call candidate set.

Use middleware when you cannot rewrite the whole agent stack, but you can insert
a retrieval layer before the LLM sees tools.

## Flow

1. Application prepares the full tool catalog.
2. Middleware builds or loads a `ToolGraph`.
3. User query is searched against the graph.
4. Only the top candidates and evidence are sent to the LLM.
5. The host application still executes the final tool call.

## Minimal Pattern

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_functions(all_tools)

def before_model_call(user_query: str, full_tools: list):
    candidates = graph.retrieve(user_query, top_k=8)
    return [tool_registry[item.name] for item in candidates]
```

## Adapter Boundary

Middleware should stay thin:

| Middleware Does | Host Application Does |
| --- | --- |
| retrieve candidates | authenticate users |
| preserve score evidence | execute tools |
| cap tool count | enforce business policy |
| classify ambiguous selection | persist audit logs |

## Diagnostics To Keep

Store or log these fields for debugging:

- query
- candidate names
- score breakdown
- selected target
- selector reason codes
- token/context reduction
- failure reason if execution fails

Do not log raw credentials or full sensitive tool outputs.

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
