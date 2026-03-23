<div align="center">

# graph-tool-call

**LLM agents can't fit thousands of tool definitions into context.**<br>
Vector search finds *similar* tools, but misses the *workflow* they belong to.<br>
**graph-tool-call** builds a tool graph and retrieves the right chain — not just one match.

<br>

| | Baseline (all tools) | graph-tool-call |
|---|:---:|:---:|
| **248 tools (K8s API)** | 12% accuracy | **82% accuracy** |
| **1068 tools (GitHub full API)** | impossible (context overflow) | **78% Recall@5** |
| **Token usage** | 8,192 tokens | 1,699 tokens (**79% reduction**) |
| **Latency (no embedding)** | — | **2.7ms avg** |

<sub>Measured with qwen3:4b (4-bit) — <a href="#benchmark">full benchmark below</a></sub>

<br>

<img src="assets/demo.gif" alt="graph-tool-call demo" width="800">

<br>

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](https://pypi.org/project/graph-tool-call/)

English · [한국어](README-ko.md) · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

## The Problem

LLM agents need tools. But as tool count grows, two things break:

1. **Context overflow** — 248 Kubernetes API endpoints = 8,192 tokens of tool definitions. The LLM chokes and accuracy drops to **12%**.
2. **Vector search misses workflows** — Searching "cancel my order" finds `cancelOrder`, but the actual flow is `listOrders → getOrder → cancelOrder → processRefund`. Vector search returns one tool; you need the chain.

**graph-tool-call** solves both. It models tool relationships as a graph, retrieves multi-step workflows via hybrid search (BM25 + graph traversal + embedding + MCP annotations), and cuts token usage by 64–91% while maintaining or improving accuracy.

### At a Glance

| What you get | How |
|---|---|
| **Workflow-aware retrieval** | Graph edges encode PRECEDES, REQUIRES, COMPLEMENTARY relations |
| **Hybrid search** | BM25 + graph traversal + embedding + MCP annotations, fused via wRRF |
| **Zero dependencies** | Core runs on Python stdlib only — add extras as needed |
| **Any tool source** | Auto-ingest from OpenAPI / Swagger / MCP / Python functions |
| **History-aware** | Previously called tools are demoted; next-step tools are boosted |
| **LangChain Gateway** | 62 tools → 2 meta-tools, **92% token reduction** per turn |
| **MCP Proxy** | 172 tools across servers → 3 meta-tools, saving ~1,200 tokens/turn |

---

## Why Not Just Vector Search?

| Scenario | Vector-only | graph-tool-call |
|----------|------------|-----------------|
| *"cancel my order"* | Returns `cancelOrder` | `listOrders → getOrder → cancelOrder → processRefund` |
| *"read and save file"* | Returns `read_file` | `read_file` + `write_file` (COMPLEMENTARY relation) |
| *"delete old records"* | Returns any tool matching "delete" | Destructive tools ranked first via MCP annotations |
| *"now cancel it"* (after listing orders) | No context from history | Demotes used tools, boosts next-step tools |
| Multiple Swagger specs with overlapping tools | Duplicate tools in results | Cross-source auto-deduplication |
| 1,200 API endpoints | Slow, noisy results | Categorized + graph traversal for precise retrieval |

---

## How It Works

```text
OpenAPI / MCP / Python functions → Ingest → Build tool graph → Hybrid retrieve → Agent
```

**Example**: User says *"cancel my order and process a refund"*

Vector search finds `cancelOrder`. But the actual workflow is:

```text
                    ┌──────────┐
          PRECEDES  │listOrders│  PRECEDES
         ┌─────────┤          ├──────────┐
         ▼         └──────────┘          ▼
   ┌──────────┐                    ┌───────────┐
   │ getOrder │                    │cancelOrder│
   └──────────┘                    └─────┬─────┘
                                        │ COMPLEMENTARY
                                        ▼
                                 ┌──────────────┐
                                 │processRefund │
                                 └──────────────┘
```

graph-tool-call returns the entire chain, not just one tool. Retrieval combines four signals via **weighted Reciprocal Rank Fusion (wRRF)**:

* **BM25** — keyword matching
* **Graph traversal** — relation-based expansion (PRECEDES, REQUIRES, COMPLEMENTARY)
* **Embedding similarity** — semantic search (optional, any provider)
* **MCP annotations** — read-only / destructive / idempotent hints

---

## Installation

The core package has **zero dependencies** — just Python standard library.
Install only what you need:

```bash
pip install graph-tool-call                    # core (BM25 + graph) — no dependencies
pip install graph-tool-call[embedding]         # + embedding, cross-encoder reranker
pip install graph-tool-call[openapi]           # + YAML support for OpenAPI specs
pip install graph-tool-call[mcp]              # + MCP server mode
pip install graph-tool-call[all]               # everything
```

<details>
<summary>All extras</summary>

| Extra | Installs | When to use |
|-------|----------|-------------|
| `openapi` | pyyaml | YAML OpenAPI specs |
| `embedding` | numpy | Semantic search (connect to Ollama/OpenAI/vLLM) |
| `embedding-local` | numpy, sentence-transformers | Local sentence-transformers models |
| `similarity` | rapidfuzz | Duplicate detection |
| `langchain` | langchain-core | LangChain integration |
| `visualization` | pyvis, networkx | HTML graph export, GraphML |
| `dashboard` | dash, dash-cytoscape | Interactive dashboard |
| `lint` | ai-api-lint | Auto-fix bad API specs |
| `mcp` | mcp | MCP server mode |

```bash
pip install graph-tool-call[lint]
pip install graph-tool-call[similarity]
pip install graph-tool-call[visualization]
pip install graph-tool-call[dashboard]
pip install graph-tool-call[langchain]
```

</details>

---

## Quick Start

### Try it in 30 seconds (no install needed)

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

```text
Query: "user authentication"
Source: https://petstore.swagger.io/v2/swagger.json (19 tools)
Results (5):

  1. getUserByName
     Get user by user name
  2. deleteUser
     Delete user
  3. createUser
     Create user
  4. loginUser
     Logs user into the system
  5. updateUser
     Updated user
```

### Python API

```python
from graph_tool_call import ToolGraph

# Build a tool graph from the official Petstore API
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# Search for tools
tools = tg.retrieve("create a new pet", top_k=5)
for t in tools:
    print(f"{t.name}: {t.description}")

# Search with workflow guidance
results = tg.retrieve_with_scores("process an order", top_k=5)
for r in results:
    print(f"{r.tool.name} [{r.confidence}]")
    for rel in r.relations:
        print(f"  → {rel.hint}")

# Execute an API directly (OpenAPI tools)
result = tg.execute(
    "addPet", {"name": "Buddy", "status": "available"},
    base_url="https://petstore3.swagger.io/api/v3",
)
```

### Workflow Planning

Unlike vector search which returns individual tools, `plan_workflow()` returns ordered execution chains with prerequisites — reducing LLM agent round-trips from 3-4 to 1.

```python
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

# Auto-generate a multi-step workflow
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

### MCP Server (Claude Code, Cursor, Windsurf, etc.)

Run as an MCP server — any MCP-compatible agent can use tool search with just a config entry:

```jsonc
// .mcp.json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve",
               "--source", "https://api.example.com/openapi.json"]
    }
  }
}
```

The MCP server also supports remote deployment via SSE and Streamable HTTP transports:

```bash
# Remote deployment (SSE transport)
graph-tool-call serve --source api.json --transport sse --host 0.0.0.0 --port 8000

# Streamable HTTP
graph-tool-call serve --source api.json --transport streamable-http --port 8000
```

Client configuration for remote MCP servers:

```json
{
  "mcpServers": {
    "tool-search": {
      "url": "http://tool-search.internal:8000/sse"
    }
  }
}
```

The server exposes 6 tools: `search_tools`, `get_tool_schema`, `execute_tool`, `list_categories`, `graph_info`, `load_source`.

Search results include **workflow guidance** — relations between tools and suggested execution order:

```json
{
  "tools": [
    {"name": "createOrder", "relations": [
      {"target": "getOrder", "type": "precedes", "hint": "Call this tool before getOrder"}
    ]},
    {"name": "getOrder", "prerequisites": ["createOrder"]}
  ],
  "workflow": {"suggested_order": ["createOrder", "getOrder", "updateOrderStatus"]}
}
```

### MCP Proxy (aggregate multiple MCP servers)

When you have many MCP servers, their tool names pile up in every LLM turn.
MCP Proxy bundles them behind a single server — **172 tools → 3 meta-tools**, saving ~1,200 tokens per turn.

**Step 1.** Create `backends.json` with your existing MCP servers:

```jsonc
// ~/backends.json
{
  "backends": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp", "--headless"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/home"]
    },
    "my-api": {
      "command": "uvx",
      "args": ["some-mcp-server"],
      "env": { "API_KEY": "sk-..." }
    }
  },
  "top_k": 10,
  "cache_path": "~/.cache/mcp-proxy-cache.json"
}
```

> **Embedding is optional.** Add `"embedding": "ollama/qwen3-embedding:0.6b"` for cross-language search (requires Ollama running). Without it, BM25 keyword search still works.

**Step 2.** Register the proxy with Claude Code:

```bash
claude mcp add -s user tool-proxy -- \
  uvx "graph-tool-call[mcp]" proxy --config ~/backends.json
```

**Step 3.** Remove the original individual servers (so they don't duplicate):

```bash
claude mcp remove playwright -s user
claude mcp remove filesystem -s user
claude mcp remove my-api -s user
```

**Step 4.** Restart Claude Code and verify:

```bash
claude mcp list
# tool-proxy: ... - ✓ Connected
# (individual servers should be gone)
```

The proxy also supports remote transport:

```bash
graph-tool-call proxy --config backends.json --transport sse --port 8000
```

That's it. The proxy exposes `search_tools`, `get_tool_schema`, and `call_backend_tool`. After searching, matched tools are **dynamically injected** for 1-hop direct calling.

#### Passthrough mode (few tools)

When total tools across all backends ≤ 30, the proxy **skips the graph layer entirely** and exposes every backend tool directly — zero overhead, no meta-tools. The LLM sees the original tool names and schemas as-is.

This is useful when you want a **single MCP entry point** for several small servers without paying the search/meta-tool tax.

```bash
# Explicitly set the threshold (default: 30)
graph-tool-call proxy --config backends.json --passthrough-threshold 50
```

Or in `backends.json`:

```jsonc
{
  "backends": { ... },
  "passthrough_threshold": 50   // tools ≤ 50 → passthrough, > 50 → gateway
}
```

| Mode | When | Exposed tools |
|------|------|---------------|
| **gateway** (default) | total tools > threshold | `search_tools` + `get_tool_schema` + `call_backend_tool` |
| **passthrough** | total tools ≤ threshold | All backend tools directly (original names/schemas) |

<details>
<summary>Alternative: .mcp.json config</summary>

```jsonc
// .mcp.json (project-level or global)
{
  "mcpServers": {
    "tool-proxy": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "proxy",
               "--config", "/path/to/backends.json"]
    }
  }
}
```

</details>

### Direct Integration (OpenAI, Ollama, vLLM, Azure, etc.)

Use `retrieve()` to search, then convert to OpenAI function-calling format. Works with **any OpenAI-compatible API**:

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
client = OpenAI()  # or OpenAI(base_url="http://localhost:11434/v1") for Ollama
response = client.chat.completions.create(
    model="gpt-4o",
    tools=openai_tools,  # only 5 relevant tools instead of all 248
    messages=[{"role": "user", "content": "create a new pet"}],
)
```

<details>
<summary>Anthropic Claude API</summary>

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

</details>

### SDK Middleware (zero code changes)

Already have tool-calling code? Add **one line** to automatically filter tools:

```python
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

patch_openai(client, graph=tg, top_k=5)  # ← add this line

# Existing code unchanged — 248 tools go in, only 5 relevant ones are sent
response = client.chat.completions.create(
    model="gpt-4o",
    tools=all_248_tools,
    messages=messages,
)
```

```python
# Also works with Anthropic
from graph_tool_call.middleware import patch_anthropic
patch_anthropic(client, graph=tg, top_k=5)
```

### Wrap Existing Tools (any format)

Already have a tool list? Wrap it with `filter_tools` — **no extra dependencies**, works with any format:

```python
from graph_tool_call import filter_tools

# Accepts any tool format:
#   LangChain BaseTool, OpenAI function dicts, MCP tool dicts,
#   Anthropic tool dicts, or plain Python functions

filtered = filter_tools(all_tools, "send an email to John", top_k=5)
# → only the 5 most relevant tools, original objects preserved
```

**Reusable toolkit** — build the graph once, filter per query:

```python
from graph_tool_call import GraphToolkit

toolkit = GraphToolkit(tools=all_tools, top_k=5)

tools_a = toolkit.get_tools("cancel my order")
tools_b = toolkit.get_tools("check the weather")

# Access the underlying ToolGraph for advanced config
toolkit.graph.enable_embedding("ollama/qwen3-embedding:0.6b")
```

### LangChain / LangGraph Agent

```bash
pip install graph-tool-call[langchain] langgraph
```

Three integration patterns — pick the one that fits your architecture:

#### Gateway Tools (recommended for large tool sets)

Convert 50~500+ tools into **2 meta-tools** (`search_tools` + `call_tool`).
The LLM searches first, then calls — no tool definitions bloat in context.

```python
from graph_tool_call.langchain import create_gateway_tools

# 62 tools from Slack, GitHub, Jira, MS365, custom APIs...
all_tools = slack_tools + github_tools + jira_tools + ms365_tools + api_tools

# Convert to 2 gateway meta-tools
gateway = create_gateway_tools(all_tools, top_k=10)
# → [search_tools, call_tool]

# Use with any LangChain agent — only 2 tools in context
agent = create_react_agent(model=llm, tools=gateway)
result = agent.invoke({"messages": [("user", "PROJ-123 이슈를 Done으로 변경해줘")]})
```

**How it works** — the LLM drives the search:

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

| | All tools bound | Gateway (2 tools) |
|---|:---:|:---:|
| **62 tools** | ~6,090 tokens/turn | ~475 tokens/turn |
| **Token reduction** | — | **92%** |
| **Accuracy** (qwen3.5:4b) | — | 70% (100% with GPT-4o) |

> Works with **any existing LangChain agent setup**. Just replace `tools=all_tools` with `tools=create_gateway_tools(all_tools)`.

#### Auto-filtering Agent (transparent per-turn filtering)

The agent automatically filters tools each turn — the LLM never sees the full list:

```python
from graph_tool_call.langchain import create_agent

# 200 tools go in — LLM sees only ~5 relevant ones each turn
agent = create_agent(llm, tools=all_200_tools, top_k=5)

result = agent.invoke({"messages": [("user", "cancel my order")]})
# Turn 1: LLM sees [cancel_order, get_order, process_refund, ...]
# Turn 2: LLM sees [next relevant tools based on conversation]
```

#### Which to use?

| Pattern | Best for | How it works |
|---------|----------|--------------|
| **Gateway** | 50+ tools, existing agents | LLM explicitly searches → calls |
| **Auto-filter** | New agents, simple setup | Transparent per-turn tool swap |
| **Manual** | Full control | You call `filter_tools()` yourself |

<details>
<summary>Manual filtering</summary>

```python
from graph_tool_call import filter_tools

filtered = filter_tools(langchain_tools, "cancel order", top_k=5)
agent = create_react_agent(llm, filtered)
```

</details>

<details>
<summary>LangChain Retriever (returns Documents instead of tools)</summary>

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

</details>

---

## Benchmark

graph-tool-call verifies two things.

1. Can performance be maintained or improved by giving the LLM only a subset of retrieved tools?
2. Does the retriever itself rank the correct tools within the top K?

The evaluation compared the following configurations on the same set of user requests.

* **baseline**: pass all tool definitions to the LLM as-is
* **retrieve-k3 / k5 / k10**: pass only the top K retrieved tools
* **+ embedding / + ontology**: add semantic search and LLM-based ontology enrichment on top of retrieve-k5

The model used was **qwen3:4b (4-bit, Ollama)**.

### Evaluation Metrics

* **Accuracy**: Did the LLM ultimately select the correct tool?
* **Recall@K**: Was the correct tool included in the top K results at the retrieval stage?
* **Avg tokens**: Average tokens passed to the LLM
* **Token reduction**: Token savings compared to baseline

### Results at a glance

* **Small-scale APIs (19~50 tools)**: baseline is already strong.
  In this range, graph-tool-call's main value is **64~91% token savings while maintaining near-baseline accuracy**.
* **Large-scale APIs (248 tools)**: baseline **collapses to 12%**.
  In contrast, graph-tool-call maintains **78~82% accuracy**. At this scale, it's not an optimization — it's closer to a **required retrieval layer**.

<details>
<summary>Full pipeline comparison</summary>

> **How to read the metrics**
>
> - **End-to-end Accuracy**: Did the LLM ultimately succeed in selecting the correct tool or performing the correct workflow?
> - **Gold Tool Recall@K**: Was the **canonical gold tool designated as the correct answer** included in the top K at the retrieval stage?
> - These two metrics measure different things, so they don't always match.
> - In particular, evaluations that accept **alternative tools** or **equivalent workflows** as correct answers may show `End-to-end Accuracy` that doesn't exactly match `Gold Tool Recall@K`.
> - **baseline** has no retrieval stage, so `Gold Tool Recall@K` does not apply.

| Dataset | Tools | Pipeline | End-to-end Accuracy | Gold Tool Recall@K | Avg tokens | Token reduction |
|---|---:|---|---:|---:|---:|---:|
| Petstore | 19 | baseline | 100.0% | — | 1,239 | — |
| Petstore | 19 | retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| Petstore | 19 | retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| Petstore | 19 | retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |
| GitHub | 50 | baseline | 100.0% | — | 3,302 | — |
| GitHub | 50 | retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| GitHub | 50 | retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| GitHub | 50 | retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |
| Mixed MCP | 38 | baseline | 96.7% | — | 2,741 | — |
| Mixed MCP | 38 | retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| Mixed MCP | 38 | retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| Mixed MCP | 38 | retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |
| Kubernetes core/v1 | 248 | baseline | 12.0% | — | 8,192 | — |
| Kubernetes core/v1 | 248 | retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding | 80.0% | 94.0% | 1,728 | 78.9% |
| Kubernetes core/v1 | 248 | retrieve-k5 + ontology | **82.0%** | 96.0% | 1,699 | 79.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding + ontology | **82.0%** | **98.0%** | 1,924 | 76.5% |

**How to read this table**

- **baseline** is the result of passing all tool definitions to the LLM without any retrieval.
- **retrieve-k** variants pass only a subset of retrieved tools to the LLM, so both retrieval quality and LLM selection ability affect performance.
- Therefore, a baseline accuracy of 100% does not mean retrieve-k accuracy must also be 100%.
- `Gold Tool Recall@K` measures whether retrieval placed the canonical gold tool in the top-k,
  while `End-to-end Accuracy` measures whether the final task execution succeeded.
- Because of this, evaluations that accept alternative tools or equivalent workflows may show the two values not exactly matching.

**Key insights**

- **Petstore / GitHub / Mixed MCP**: When tool count is small or medium, baseline is already strong.
  In this range, graph-tool-call's main value is **significantly reducing tokens without much accuracy loss**.
- **Kubernetes core/v1 (248 tools)**: When tool count is large, baseline collapses due to context overload.
  graph-tool-call recovers performance from **12.0% to 78.0~82.0%** by narrowing candidates through retrieval.
- In practice, **retrieve-k5** is the best default.
  It offers a good balance of token efficiency and performance. On large datasets, adding embedding / ontology yields further improvement.

</details>

### Retrieval performance: Does the retriever find the correct tools in the top K?

The table below measures the quality of retrieval itself, **before the LLM stage**.
Only **BM25 + graph traversal** were used here — no embedding or ontology.

> **How to read the metrics**
>
> - **Gold Tool Recall@K**: Was the **canonical gold tool designated as the correct answer** included in the top K at the retrieval stage?
> - This table shows **how well the retriever constructs the candidate set**, not the final LLM selection accuracy.
> - Therefore, this table should be read together with the **End-to-end Accuracy** table above.
> - Even if retrieval places the gold tool in the top-k, the final LLM doesn't always select the correct answer.
> - Conversely, in end-to-end evaluations that accept **alternative tools** or **equivalent workflows** as correct, the final accuracy and gold recall may not exactly match.

| Dataset | Tools | Gold Tool Recall@3 | Gold Tool Recall@5 | Gold Tool Recall@10 |
|---|---:|---:|---:|---:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub | 50 | 87.5% | **87.5%** | 92.5% |
| Mixed MCP | 38 | 93.3% | **96.7%** | 100.0% |
| Kubernetes core/v1 | 248 | 82.0% | **91.0%** | 92.0% |

### How to read this table

- **Gold Tool Recall@K** shows the retriever's ability to include the correct tool in the candidate set.
- On small datasets, `k=5` alone achieves high recall.
- On large datasets, increasing `k` raises recall, but also increases the tokens passed to the LLM.
- In practice, you should consider not just recall but also **token cost** and **final end-to-end accuracy** together.

### Key insights

- **Petstore / Mixed MCP**: `k=5` alone includes nearly all correct tools in the candidate set.
- **GitHub**: There is a recall gap between `k=5` and `k=10`, so `k=10` may be better if higher recall is needed.
- **Kubernetes core/v1**: Even with a large number of tools, `k=5` already achieves **91.0%** gold recall.
  The retrieval stage alone can significantly compress the candidate set while retaining most correct tools.
- Overall, **`retrieve-k5` is the most practical default**.
  `k=3` is lighter but may miss some correct tools, while `k=10` may increase token costs relative to recall gains.

### When do embedding and ontology help?

On the largest dataset, **Kubernetes core/v1 (248 tools)**, we compared adding extra signals on top of `retrieve-k5`.

| Pipeline | End-to-end Accuracy | Gold Tool Recall@5 | Interpretation |
|---|---:|---:|---|
| retrieve-k5 | 78.0% | 91.0% | BM25 + graph alone is a strong baseline |
| + embedding | 80.0% | 94.0% | Recovers queries that are semantically similar but differently worded |
| + ontology | **82.0%** | 96.0% | LLM-generated keywords/example queries significantly improve retrieval quality |
| + embedding + ontology | **82.0%** | **98.0%** | Accuracy maintained, gold recall at its highest |

### Summary

- **Embedding** compensates for **semantic similarity** that BM25 misses.
- **Ontology** **expands the searchable representation itself** when tool descriptions are short or non-standard.
- Using both together may show limited additional gains in end-to-end accuracy, but **the ability to include correct tools in the candidate set becomes strongest**.

### Competitive Benchmark (retrieval strategies)

Compared 6 retrieval strategies across 9 datasets (19–1068 tools):

| Strategy | Recall@5 | MRR | Latency |
|---|:---:|:---:|:---:|
| Vector Only (≈bigtool) | 96.8% | 0.897 | 176ms |
| BM25 Only | 91.6% | 0.819 | 1.5ms |
| BM25 + Graph (default) | 91.6% | 0.819 | 14ms |
| Full Pipeline (with embedding) | 96.8% | 0.897 | 172ms |

**Key finding**: Without embedding, BM25+Graph achieves 91.6% Recall — competitive with vector search at 65x faster speed. With embedding enabled, performance matches pure vector search.

### Scale Test: 1068 tools (GitHub full API)

| Strategy | Recall@5 | MRR | Miss% |
|---|:---:|:---:|:---:|
| Vector Only | 88.0% | 0.761 | 12.0% |
| BM25 + Graph | 78.0% | 0.643 | 22.0% |
| Full Pipeline | 88.0% | 0.761 | 12.0% |

### Reproduce it

```bash
# Retrieval quality (fast, no LLM needed)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# Pipeline benchmark (LLM comparison)
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# Save baseline and compare
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

---

## Basic Usage

### From OpenAPI / Swagger

```python
from graph_tool_call import ToolGraph

# From file (JSON / YAML)
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# From URL — auto-discovers all spec groups from Swagger UI
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# With caching — build once, reload instantly
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",
)

# Supports: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
```

### From MCP Server Tools

```python
from graph_tool_call import ToolGraph

mcp_tools = [
    {
        "name": "read_file",
        "description": "Read a file",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "delete_file",
        "description": "Delete a file permanently",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]

tg = ToolGraph()
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

tools = tg.retrieve("delete temporary files", top_k=5)
```

MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are used as retrieval signals.
Query intent is automatically classified — read queries prioritize read-only tools, delete queries prioritize destructive tools.

### Directly From an MCP Server

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Public MCP endpoint
tg.ingest_mcp_server("https://mcp.example.com/mcp")

# Local/private MCP endpoint (explicit opt-in)
tg.ingest_mcp_server(
    "http://127.0.0.1:3000/mcp",
    allow_private_hosts=True,
)
```

`ingest_mcp_server()` calls HTTP JSON-RPC `tools/list`, fetches the tool list,
then ingests it with MCP annotations preserved.

Remote ingest safety defaults:
- private / localhost hosts are blocked by default
- remote response size is capped
- redirects are limited
- unexpected content types are rejected

### From Python Functions

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """Read contents of a file."""

def write_file(path: str, content: str) -> None:
    """Write contents to a file."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
```

Parameters are extracted from type hints, descriptions from docstrings.

### Manual Tool Registration

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

tg.add_tools([
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    },
])

tg.add_relation("get_weather", "get_forecast", "complementary")
```

---

## Embedding-based Hybrid Search

Add embedding-based semantic search on top of BM25 + graph.
No heavy dependencies needed — use any external embedding server (Ollama, OpenAI, vLLM, etc.)
or local sentence-transformers.

```bash
pip install graph-tool-call[embedding]           # numpy only (~20MB)
pip install graph-tool-call[embedding-local]      # + sentence-transformers (~2GB, local models)
```

```python
# Ollama (recommended — lightweight, cross-language)
tg.enable_embedding("ollama/qwen3-embedding:0.6b")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# vLLM / llama.cpp / any OpenAI-compatible server
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")

# Sentence-transformers (requires embedding-local extra)
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# Custom callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

Weights are automatically rebalanced when embedding is enabled. You can fine-tune them:

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

---

## Save and Load

Build once, reuse everywhere. The full graph structure (nodes, edges, relation types, weights) is preserved.

```python
# Save
tg.save("my_graph.json")

# Load
tg = ToolGraph.load("my_graph.json")

# Or use cache= in from_url() for automatic save/load
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

When embedding search is enabled, saved graphs also preserve:
- embedding vectors
- restorable embedding provider config when available
- retrieval weights
- diversity settings

This lets `ToolGraph.load()` restore hybrid retrieval state without rebuilding embeddings from scratch.

### Analysis and Dashboard

```python
report = tg.analyze()
print(report.orphan_tools)

app = tg.dashboard_app()
# or: tg.dashboard(port=8050)
```

`analyze()` builds an operational summary with duplicates, conflicts, orphan tools,
category coverage, and relation counts. `dashboard()` launches the interactive
Dash Cytoscape UI for graph inspection and retrieval testing.

---

## Advanced Features

### Cross-Encoder Reranking

Second-stage reranking using a cross-encoder model.

```python
tg.enable_reranker()  # default: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("cancel order", top_k=5)
```

After narrowing candidates with wRRF, `(query, tool_description)` pairs are jointly encoded for more precise ranking.

### MMR Diversity

Reduces redundant results to secure more diverse candidates.

```python
tg.enable_diversity(lambda_=0.7)
```

### History-Aware Retrieval

Pass previously called tool names to improve next-step retrieval.

```python
# First call
tools = tg.retrieve("find my order")
# → [listOrders, getOrder, ...]

# Second call
tools = tg.retrieve("now cancel it", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
```

Already-used tools are demoted, and tools closer to the next step in the graph are boosted.

### wRRF Weight Tuning

Adjust the contribution of each signal.

```python
tg.set_weights(
    keyword=0.2,     # BM25 text matching
    graph=0.5,       # graph traversal
    embedding=0.3,   # semantic similarity
    annotation=0.2,  # MCP annotation matching
)
```

### LLM-Enhanced Ontology

Build richer tool ontologies using any LLM.
Useful for category generation, relation inference, and search keyword expansion.

```python
tg.auto_organize(llm="ollama/qwen2.5:7b")
tg.auto_organize(llm=lambda p: my_llm(p))
tg.auto_organize(llm=openai.OpenAI())
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")
```

<details>
<summary>Supported LLM inputs</summary>

| Input | Wrapped as |
|-------|-----------|
| `OntologyLLM` instance | Pass-through |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAI client (has `chat.completions`) | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completion wrapper |

</details>

### Duplicate Detection

Find and merge duplicate tools across multiple API specs.

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### Export and Visualization

```python
# Interactive HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (Gephi, yEd)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint Integration

Auto-fix poor OpenAPI specs before ingestion using [ai-api-lint](https://github.com/SonAIengine/ai-api-lint).

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)
```

---

## CLI Reference

```bash
# One-liner search (ingest + retrieve in one step)
graph-tool-call search "cancel order" --source https://api.example.com/openapi.json
graph-tool-call search "delete user" --source ./openapi.json --scores --json

# MCP server
graph-tool-call serve --source https://api.example.com/openapi.json
graph-tool-call serve --graph prebuilt.json
graph-tool-call serve -s https://api1.com/spec.json -s https://api2.com/spec.json

# Build and save graph
graph-tool-call ingest https://api.example.com/openapi.json -o graph.json
graph-tool-call ingest ./spec.yaml --embedding --organize

# Search from pre-built graph
graph-tool-call retrieve "query" -g graph.json -k 10

# Analyze, visualize, dashboard
graph-tool-call analyze graph.json --duplicates --conflicts
graph-tool-call visualize graph.json -f html
graph-tool-call info graph.json
graph-tool-call dashboard graph.json --port 8050
```

---

## Full API Reference

<details>
<summary><code>ToolGraph</code> methods</summary>

| Method | Description |
|--------|-------------|
| `add_tool(tool)` | Add a single tool (auto-detects format) |
| `add_tools(tools)` | Add multiple tools |
| `ingest_openapi(source)` | Ingest from OpenAPI / Swagger spec |
| `ingest_mcp_tools(tools)` | Ingest from MCP tool list |
| `ingest_mcp_server(url)` | Fetch and ingest from MCP HTTP server |
| `ingest_functions(fns)` | Ingest from Python callables |
| `ingest_arazzo(source)` | Ingest Arazzo 1.0.0 workflow spec |
| `from_url(url, cache=...)` | Build from Swagger UI or spec URL |
| `add_relation(src, tgt, type)` | Add a manual relation |
| `auto_organize(llm=...)` | Auto-categorize tools |
| `build_ontology(llm=...)` | Build complete ontology |
| `retrieve(query, top_k=10)` | Search for tools |
| `validate_tool_call(call)` | Validate and auto-correct a tool call |
| `assess_tool_call(call)` | Return `allow` / `confirm` / `deny` decision |
| `enable_embedding(provider)` | Enable hybrid embedding search |
| `enable_reranker(model)` | Enable cross-encoder reranking |
| `enable_diversity(lambda_)` | Enable MMR diversity |
| `set_weights(...)` | Tune wRRF fusion weights |
| `find_duplicates(threshold)` | Find duplicate tools |
| `merge_duplicates(pairs)` | Merge detected duplicates |
| `apply_conflicts()` | Detect and add CONFLICTS_WITH edges |
| `analyze()` | Build operational analysis summary |
| `save(path)` / `load(path)` | Serialize / deserialize |
| `export_html(path)` | Export interactive HTML visualization |
| `export_graphml(path)` | Export to GraphML format |
| `export_cypher(path)` | Export as Neo4j Cypher statements |
| `dashboard_app()` / `dashboard()` | Build or launch interactive dashboard |
| `suggest_next(tool, history=...)` | Suggest next tools based on graph |

</details>

---

## Feature Comparison

| Feature | Vector-only solutions | graph-tool-call |
|---------|----------------------|-----------------|
| Dependencies | Embedding model required | **Zero** (core runs on stdlib) |
| Tool source | Manual registration | Auto-ingest from Swagger / OpenAPI / MCP |
| Search method | Flat vector similarity | Multi-stage hybrid (wRRF + rerank + MMR) |
| Behavioral semantics | None | MCP annotation-aware retrieval |
| Tool relations | None | 6 relation types, auto-detected |
| Call ordering | None | State machine + CRUD + response→request data flow |
| Deduplication | None | Cross-source duplicate detection |
| Ontology | None | Auto / LLM-Auto modes |
| History awareness | None | Demotes used tools, boosts next-step |
| Spec quality | Assumes good specs | ai-api-lint auto-fix integration |
| LLM dependency | Required | Optional (better with, works without) |

---

## Documentation

| Doc | Description |
|-----|-------------|
| [Architecture](docs/architecture/overview.md) | System overview, pipeline layers, data model |
| [WBS](docs/wbs/) | Work Breakdown Structure — Phase 0~4 progress |
| [Design](docs/design/) | Algorithm design — spec normalization, dependency detection, search modes, call ordering, ontology modes |
| [Research](docs/research/) | Competitive analysis, API scale data, commerce patterns |
| [Release Checklist](docs/release-checklist.md) | Release process, changelog flow, pre-release checks |
| [OpenAPI Guide](docs/design/openapi-guide.md) | How to write API specs that produce better tool graphs |

---

## Contributing

Contributions are welcome.

```bash
# Development setup
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev --all-extras   # install all optional deps for full test coverage

# Run tests
poetry run pytest -v

# Lint
poetry run ruff check .
poetry run ruff format --check .

# Run benchmarks
python -m benchmarks.run_benchmark -v
```

---

## License

[MIT](LICENSE)
