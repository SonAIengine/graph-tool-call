---
title: LangChain
description: Use graph-tool-call retrieval with LangChain tool adapters.
---

# LangChain

Use graph-tool-call as a retrieval and filtering layer before constructing the
LangChain tool set sent to a model. The goal is to keep the LLM's visible tool
catalog small while preserving evidence about why each candidate was included.

## Basic Pattern

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_functions(langchain_tools)

def tools_for_query(query: str):
    candidates = graph.retrieve(query, top_k=8)
    names = {candidate.name for candidate in candidates}
    return [tool for tool in langchain_tools if tool.name in names]
```

## Gateway Tools

If your agent framework prefers a small fixed set of tools, expose search as a
gateway tool instead of exposing every downstream operation.

```python
from graph_tool_call import create_gateway_tools

gateway_tools = create_gateway_tools(
    graph,
    top_k=8,
)
```

The model asks the gateway to search; the application can then present or
execute the selected downstream tool according to its own policy.

## Recommended Controls

| Control | Why |
| --- | --- |
| `top_k` | Limits visible tool count |
| score evidence | Explains why candidates were shown |
| target selector guard | Prevents obvious LLM target mismatch |
| Quality Lab cases | Catches regressions before catalog widening |
| host-side execution | Keeps auth and side effects under application control |

## Common Pitfalls

- Passing every LangChain tool to the model after retrieval.
- Dropping score/evidence metadata, making failures hard to debug.
- Letting the engine own runtime credentials.
- Treating a search hit as proof that plan and execute are ready.

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Public API](../reference/public-api.md)
