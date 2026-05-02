# LangChain / LangGraph Integration

```bash
pip install graph-tool-call[langchain] langgraph
```

Three integration patterns — pick the one that fits your architecture.

| Pattern | Best for | How it works |
|---|---|---|
| **Gateway** | 50+ tools, existing agents | LLM explicitly searches → calls |
| **Auto-filter** | New agents, simple setup | Transparent per-turn tool swap |
| **Manual** | Full control | You call `filter_tools()` yourself |

---

## 1. Gateway Tools (recommended for large tool sets)

Convert 50~500+ tools into **2 meta-tools** (`search_tools` + `call_tool`). The LLM searches first, then calls — no tool definitions bloat in context.

```python
from graph_tool_call.langchain import create_gateway_tools

# 62 tools from Slack, GitHub, Jira, MS365, custom APIs...
all_tools = slack_tools + github_tools + jira_tools + ms365_tools + api_tools

# Convert to 2 gateway meta-tools
gateway = create_gateway_tools(all_tools, top_k=10)
# → [search_tools, call_tool]

# Use with any LangChain agent — only 2 tools in context
agent = create_react_agent(model=llm, tools=gateway)
result = agent.invoke({
    "messages": [("user", "PROJ-123 이슈를 Done으로 변경해줘")]
})
```

### How it works

```text
User: "Cancel order #500"
  ↓
LLM calls search_tools(query="cancel order")
  → returns: cancel_order, get_order, process_refund (with parameter info)
  ↓
LLM calls call_tool(tool_name="cancel_order", arguments={"order_id": 500})
  → returns: {"order_id": 500, "status": "cancelled"}
  ↓
LLM: "Order #500 has been cancelled."
```

### Token impact

| | All tools bound | Gateway (2 tools) |
|---|:---:|:---:|
| **62 tools** | ~6,090 tokens/turn | ~475 tokens/turn |
| **Token reduction** | — | **92%** |
| **Accuracy** (qwen3.5:4b) | — | 70% (100% with GPT-4o) |

> Works with **any existing LangChain agent setup**. Just replace `tools=all_tools` with `tools=create_gateway_tools(all_tools)`.

See the [200-tool LangChain agent benchmark](../benchmarks.md#6-langchain-agent-benchmark-200-tools) for results across GPT and Claude models.

---

## 2. Auto-filtering Agent (transparent per-turn filtering)

The agent automatically filters tools each turn — the LLM never sees the full list.

```python
from graph_tool_call.langchain import create_agent

# 200 tools go in — LLM sees only ~5 relevant ones each turn
agent = create_agent(llm, tools=all_200_tools, top_k=5)

result = agent.invoke({"messages": [("user", "cancel my order")]})
# Turn 1: LLM sees [cancel_order, get_order, process_refund, ...]
# Turn 2: LLM sees [next relevant tools based on conversation]
```

---

## 3. Manual filtering

```python
from graph_tool_call import filter_tools
from langgraph.prebuilt import create_react_agent

filtered = filter_tools(langchain_tools, "cancel order", top_k=5)
agent = create_react_agent(llm, filtered)
```

---

## LangChain Retriever (returns Documents)

If you want to use graph-tool-call as a regular retriever returning `Document` objects (e.g., for a chain that doesn't use tool-calling):

```python
from graph_tool_call import ToolGraph
from graph_tool_call.langchain import GraphToolRetriever

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

retriever = GraphToolRetriever(tool_graph=tg, top_k=5)
docs = retriever.invoke("cancel an order")

for doc in docs:
    print(doc.page_content)       # "cancelOrder: Cancel an existing order"
    print(doc.metadata["tags"])   # ["order"]
```
