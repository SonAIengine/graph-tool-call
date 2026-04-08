# Direct API Integration

Use `retrieve()` to search, then convert results to your provider's tool format. Works with **any OpenAI-compatible API** (OpenAI, Azure, Ollama, vLLM, llama.cpp) and Anthropic.

## OpenAI / OpenAI-compatible

```python
from openai import OpenAI
from graph_tool_call import ToolGraph
from graph_tool_call.langchain.tools import tool_schema_to_openai_function

# Build graph from any source
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

# Retrieve only the relevant tools for a query
tools = tg.retrieve("create a new pet", top_k=5)

# Convert to OpenAI function-calling format
openai_tools = [
    {"type": "function", "function": tool_schema_to_openai_function(t)}
    for t in tools
]

# Use with any provider — OpenAI, Azure, Ollama, vLLM, llama.cpp, etc.
client = OpenAI()
# Or for Ollama: OpenAI(base_url="http://localhost:11434/v1")

response = client.chat.completions.create(
    model="gpt-4o",
    tools=openai_tools,  # only 5 relevant tools instead of all 248
    messages=[{"role": "user", "content": "create a new pet"}],
)
```

## Anthropic Claude

```python
from anthropic import Anthropic
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url("https://api.example.com/openapi.json")
tools = tg.retrieve("cancel an order", top_k=5)

# Convert to Anthropic tool format
anthropic_tools = [
    {
        "name": t.name,
        "description": t.description,
        "input_schema": {
            "type": "object",
            "properties": {
                p.name: {"type": p.type, "description": p.description}
                for p in t.parameters
            },
            "required": [p.name for p in t.parameters if p.required],
        },
    }
    for t in tools
]

client = Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=anthropic_tools,
    messages=[{"role": "user", "content": "cancel my order"}],
    max_tokens=1024,
)
```

## Wrap any tool list (no graph needed)

If you already have a list of tools in any format (LangChain `BaseTool`, OpenAI dicts, MCP dicts, Anthropic dicts, plain Python functions), use `filter_tools` directly — **no extra dependencies**:

```python
from graph_tool_call import filter_tools

filtered = filter_tools(all_tools, "send an email to John", top_k=5)
# → only the 5 most relevant tools, original objects preserved
```

### Reusable toolkit

Build the graph once, filter per query:

```python
from graph_tool_call import GraphToolkit

toolkit = GraphToolkit(tools=all_tools, top_k=5)

tools_a = toolkit.get_tools("cancel my order")
tools_b = toolkit.get_tools("check the weather")

# Access the underlying ToolGraph for advanced config
toolkit.graph.enable_embedding("ollama/qwen3-embedding:0.6b")
```

## Workflow planning

Beyond per-query filtering, `plan_workflow()` returns ordered execution chains with prerequisites — reducing agent round-trips from 3-4 to 1.

```python
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

plan = tg.plan_workflow("process a refund")
for step in plan.steps:
    print(f"{step.order}. {step.tool.name} — {step.reason}")
# 1. getOrder — prerequisite for requestRefund
# 2. requestRefund — primary action

# Edit the workflow
plan.remove_step("listOrders")
plan.insert_step(0, "getOrder", tools=tg.tools, reason="need order ID")
plan.set_param_mapping("requestRefund", "order_id", "getOrder.response.id")

# Visual editor (opens in browser)
plan.open_editor(tools=tg.tools)

# Save / Load
plan.save("refund_workflow.json")
```
