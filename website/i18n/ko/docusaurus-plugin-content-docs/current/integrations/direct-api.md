---
title: Direct API
description: framework adapter 없이 application code에서 graph-tool-call을 직접 호출합니다.
---

# Direct API

Direct API는 ingest, retrieval, selection, planning, execution integration을 직접
제어하고 싶을 때 사용합니다.

## Minimal Flow

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
candidates = graph.retrieve_with_scores("고객 주문 조회", top_k=8)
```

## 관련 문서

- [Public API](../reference/public-api.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
