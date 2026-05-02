# SDK Middleware

Already have tool-calling code? Add **one line** to automatically filter tools through graph-tool-call. Existing code stays unchanged.

## OpenAI

```python
from openai import OpenAI
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai

client = OpenAI()
tg = ToolGraph.from_url("https://api.example.com/openapi.json")

patch_openai(client, graph=tg, top_k=5)  # ← add this line

# Existing code unchanged — 248 tools go in, only 5 relevant ones are sent
response = client.chat.completions.create(
    model="gpt-4o",
    tools=all_248_tools,
    messages=messages,
)
```

## Anthropic

```python
from anthropic import Anthropic
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_anthropic

client = Anthropic()
tg = ToolGraph.from_url("https://api.example.com/openapi.json")

patch_anthropic(client, graph=tg, top_k=5)  # ← add this line

# Existing code unchanged
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=all_248_tools,
    messages=messages,
    max_tokens=1024,
)
```

## How it works

The middleware monkey-patches `chat.completions.create` (OpenAI) or `messages.create` (Anthropic) so that whenever `tools=...` is passed, it:

1. Reads the latest user message
2. Calls `graph.retrieve(query, top_k=top_k)`
3. Replaces `tools=` with the filtered subset
4. Forwards the request

The original tool list never reaches the model. There's no change to the SDK return type, streaming, or async behavior.

## When to use

| Use middleware when... | Use direct API when... |
|---|---|
| You have working tool-calling code already | You're starting from scratch |
| You don't want to refactor for retrieval | You want explicit control over which tools are sent |
| Tool list comes from a runtime registry | Tool list is static and known |

For explicit retrieval control, see [Direct API integration](direct-api.md).
