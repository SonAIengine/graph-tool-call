---
title: Direct API
description: Call graph-tool-call directly from application code without a framework adapter.
---

# Direct API

Use the direct API when you want full control over ingest, retrieval, selection,
planning, and execution integration.

## Minimal Flow

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
candidates = graph.retrieve_with_scores("find customer orders", top_k=8)
```

## Related Pages

- [Public API](../reference/public-api.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
