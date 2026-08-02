---
title: Middleware
description: Use middleware to filter model tool catalogs before invocation.
---

# Middleware

Middleware integrations intercept the tool catalog before a model invocation and
replace a large raw catalog with a compact graph-tool-call candidate set.

Use middleware when you cannot rewrite the whole agent stack, but you can insert
a retrieval layer before the LLM sees tools.

This is the lowest-friction integration path. It does not change the host
application's execution layer; it only reduces and explains the tool list sent
to the model.

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

## OpenAI Client Patch

```python
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai, unpatch_openai

graph = ToolGraph()
graph.add_tools(openai_tools)

patch_openai(client, graph=graph, top_k=5, min_tools=10)

response = client.responses.create(
    model="gpt-5",
    tools=openai_tools,
    input="delete a user account",
)

unpatch_openai(client)
```

`min_tools` prevents filtering very small catalogs where the extra retrieval
step is not useful.

The same patch also covers legacy `client.chat.completions.create` calls. Hosted
Responses tools such as `web_search` are preserved; only named function tools
are retrieved and reduced.

## Anthropic Client Patch

```python
from graph_tool_call.middleware import patch_anthropic

patch_anthropic(client, graph=graph, top_k=5)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=anthropic_tools,
    messages=[{"role": "user", "content": "find customer orders"}],
)
```

The middleware extracts the latest user message and uses it as the retrieval
query. For multi-turn references such as "cancel that one", use a higher-level
adapter that generates a compact search query from conversation state.

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

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| all tools still sent | no user message, no tools, or tool count below `min_tools` | inspect request shape and `min_tools` |
| wrong candidate set | graph lacks metadata or query context is too short | use evidence output and add aliases/contracts |
| patch applied twice | client already patched | call `unpatch_*()` before re-patching |
| selected tool cannot execute | middleware only filters; host still owns execution | inspect host auth/request layer |

## Validation

```bash
poetry run pytest tests/test_middleware.py -q
```

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
