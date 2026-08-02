---
title: LangChain
description: Use graph-tool-call retrieval with LangChain tool adapters.
---

# LangChain

Use graph-tool-call as a retrieval and filtering layer before constructing the
LangChain tool set sent to a model. The goal is to keep the LLM's visible tool
catalog small while preserving evidence about why each candidate was included.

Use this integration when you already have LangChain tools and want per-query
tool filtering without changing downstream tool implementations.

## Basic Pattern

```python
from graph_tool_call.langchain import filter_tools

filtered = filter_tools(langchain_tools, "cancel an order", top_k=8)
```

`filter_tools()` preserves the original tool objects. The returned objects are
the same LangChain tools your agent already knows how to call.

## Reusable Toolkit

Build the graph once and filter many times:

```python
from graph_tool_call.langchain import GraphToolkit

toolkit = GraphToolkit(langchain_tools, top_k=8)

def tools_for_turn(user_query: str):
    return toolkit.get_tools(user_query)
```

The underlying `toolkit.graph` can be inspected, saved, or reused in tests.

## LangChain v1 Middleware

Use the official model-call middleware extension point:

```python
from langchain.agents import create_agent
from graph_tool_call.langchain import create_tool_selection_middleware

selection = create_tool_selection_middleware(langchain_tools, top_k=5)
agent = create_agent(
    model,
    tools=langchain_tools,
    middleware=[selection],
)
```

The middleware filters pre-registered tools before each model call. It only
intersects with tools still available on the request, so an earlier permission
or feature-flag middleware cannot be bypassed.

## Legacy LangGraph Agent

For LangGraph ReAct agents:

```python
from graph_tool_call.langchain import create_agent

agent = create_agent(
    model,
    tools=langchain_tools,
    top_k=5,
    query_mode="message",
)
```

`query_mode="message"` uses the latest user message as the retrieval query. Use
`query_mode="llm"` only when multi-turn references need a generated search
query; it adds one LLM call per turn.

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

## Choosing A Pattern

| Pattern | Use When | Tradeoff |
| --- | --- | --- |
| `filter_tools()` | one-shot filtering before an agent call | rebuilds unless a graph is provided |
| `GraphToolkit` | same catalog reused across many turns | simple and explicit |
| LangChain v1 middleware | `create_agent` should filter every model turn | recommended current integration |
| `create_agent()` | LangGraph ReAct flow should filter per turn | framework-specific |
| gateway tools | model should call search explicitly | requires extra tool-call step |

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

## Validation

```bash
poetry run pytest tests/test_langchain_toolkit.py tests/test_langchain_middleware.py tests/test_langchain_agent.py -q
```

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Public API](../reference/public-api.md)
