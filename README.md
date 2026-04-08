<div align="center">

# graph-tool-call

**LLM agents can't fit thousands of tool definitions into context.**<br>
Vector search finds *similar* tools, but misses the *workflow* they belong to.<br>
**graph-tool-call** builds a tool graph and retrieves the right chain — not just one match.

<br>

| | Without retrieval | graph-tool-call |
|---|:---:|:---:|
| **248 tools (K8s API)** | 12% accuracy | **82% accuracy** |
| **1068 tools (GitHub full API)** | context overflow | **78% Recall@5** |
| **Token usage** | 8,192 tok | **1,699 tok** (79% ↓) |

<sub>Measured with qwen3:4b (4-bit) — <a href="docs/benchmarks.md">full benchmark</a></sub>

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

<details>
<summary><b>Table of Contents</b></summary>

- [Why](#why)
- [How it works](#how-it-works)
- [Install](#install)
- [Quick Start](#quick-start)
- [Choose your integration](#choose-your-integration)
- [Benchmark](#benchmark)
- [Advanced](#advanced)
- [Docs](#docs)
- [Contributing](#contributing)

</details>

---

## Why

LLM agents need tools. But as tool count grows, two things break:

1. **Context overflow** — 248 Kubernetes API endpoints = 8,192 tokens of tool definitions. The LLM chokes and accuracy drops to **12%**.
2. **Vector search misses workflows** — Searching *"cancel my order"* finds `cancelOrder`, but the actual flow is `listOrders → getOrder → cancelOrder → processRefund`. Vector search returns one tool; you need the chain.

**graph-tool-call** solves both. It models tool relationships as a graph, retrieves multi-step workflows via hybrid search (BM25 + graph traversal + embedding + MCP annotations), and cuts token usage by 64–91% while maintaining or improving accuracy.

| Scenario | Vector-only | graph-tool-call |
|----------|------------|-----------------|
| *"cancel my order"* | Returns `cancelOrder` | `listOrders → getOrder → cancelOrder → processRefund` |
| *"read and save file"* | Returns `read_file` | `read_file` + `write_file` (COMPLEMENTARY relation) |
| *"delete old records"* | Returns any tool matching "delete" | Destructive tools ranked first via MCP annotations |
| *"now cancel it"* (after listing orders) | No context from history | Demotes used tools, boosts next-step tools |
| Multiple Swagger specs with overlapping tools | Duplicate tools in results | Cross-source auto-deduplication |
| 1,200 API endpoints | Slow, noisy results | Categorized + graph traversal for precise retrieval |

---

## How it works

```text
OpenAPI / MCP / Python functions → Ingest → Build tool graph → Hybrid retrieve → Agent
```

**Example** — User says *"cancel my order and process a refund"*

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

## Install

The core package has **zero dependencies** — just Python standard library. Install only what you need:

```bash
pip install graph-tool-call                # core (BM25 + graph) — no dependencies
pip install graph-tool-call[embedding]     # + embedding, cross-encoder reranker
pip install graph-tool-call[openapi]       # + YAML support for OpenAPI specs
pip install graph-tool-call[mcp]           # + MCP server / proxy mode
pip install graph-tool-call[all]           # everything
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
| `mcp` | mcp | MCP server / proxy mode |

</details>

---

## Quick Start

### Try it in 30 seconds (no install)

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

```text
Query: "user authentication"
Source: https://petstore.swagger.io/v2/swagger.json (19 tools)
Results (5):

  1. getUserByName  — Get user by user name
  2. deleteUser     — Delete user
  3. createUser     — Create user
  4. loginUser      — Logs user into the system
  5. updateUser     — Updated user
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

# Execute an OpenAPI tool directly
result = tg.execute(
    "addPet", {"name": "Buddy", "status": "available"},
    base_url="https://petstore3.swagger.io/api/v3",
)
```

### Workflow planning

`plan_workflow()` returns ordered execution chains with prerequisites — reducing agent round-trips from 3-4 to 1.

```python
plan = tg.plan_workflow("process a refund")
for step in plan.steps:
    print(f"{step.order}. {step.tool.name} — {step.reason}")
# 1. getOrder      — prerequisite for requestRefund
# 2. requestRefund — primary action

plan.save("refund_workflow.json")
```

Edit, parameterize, and visualize workflows — see [Direct API guide](docs/integrations/direct-api.md#workflow-planning).

### Other tool sources

```python
# From an MCP server (HTTP JSON-RPC tools/list)
tg.ingest_mcp_server("https://mcp.example.com/mcp")

# From an MCP tool list (annotations preserved)
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

# From Python callables (type hints + docstrings)
tg.ingest_functions([read_file, write_file])
```

MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are used as retrieval signals — query intent is automatically classified, and read queries prioritize read-only tools while delete queries prioritize destructive tools.

---

## Choose your integration

graph-tool-call ships several integration patterns. Pick the one that matches your stack:

| You're using... | Pattern | Token win | Guide |
|---|---|:---:|---|
| Claude Code / Cursor / Windsurf | **MCP Proxy** (aggregate N MCP servers → 3 meta-tools) | ~1,200 tok/turn | [docs/integrations/mcp-proxy.md](docs/integrations/mcp-proxy.md) |
| Any MCP-compatible client | **MCP Server** (single source as MCP) | varies | [docs/integrations/mcp-server.md](docs/integrations/mcp-server.md) |
| LangChain / LangGraph (50+ tools) | **Gateway tools** (N tools → 2 meta-tools) | **92%** | [docs/integrations/langchain.md](docs/integrations/langchain.md) |
| OpenAI / Anthropic SDK (existing code) | **Middleware** (1-line monkey-patch) | 76–91% | [docs/integrations/middleware.md](docs/integrations/middleware.md) |
| Direct control over retrieval | **Python API** (`retrieve()` + format adapter) | varies | [docs/integrations/direct-api.md](docs/integrations/direct-api.md) |

### MCP Proxy (most common)

When you have many MCP servers, their tool names pile up in every LLM turn. Bundle them behind one server: **172 tools → 3 meta-tools**.

```bash
# 1. Create ~/backends.json listing your MCP servers
# 2. Register the proxy with Claude Code
claude mcp add -s user tool-proxy -- \
  uvx "graph-tool-call[mcp]" proxy --config ~/backends.json
```

Full setup, passthrough mode, remote transport → [MCP Proxy guide](docs/integrations/mcp-proxy.md).

### LangChain Gateway

```python
from graph_tool_call.langchain import create_gateway_tools

# 62 tools from Slack, GitHub, Jira, MS365...
gateway = create_gateway_tools(all_tools, top_k=10)
# → [search_tools, call_tool] — only 2 tools in context

agent = create_react_agent(model=llm, tools=gateway)
```

92% token reduction vs binding all 62 tools. See [LangChain guide](docs/integrations/langchain.md) for auto-filter and manual patterns.

### SDK middleware

```python
from graph_tool_call.middleware import patch_openai

patch_openai(client, graph=tg, top_k=5)  # ← add this one line

# Existing code unchanged — 248 tools go in, only 5 relevant ones are sent
response = client.chat.completions.create(
    model="gpt-4o",
    tools=all_248_tools,
    messages=messages,
)
```

Also works with Anthropic via `patch_anthropic`. See [Middleware guide](docs/integrations/middleware.md).

---

## Benchmark

Two questions: (1) Does the LLM still pick the right tool when given only the retrieved subset? (2) Does the retriever itself rank correct tools in the top K?

| Dataset | Tools | Baseline acc | graph-tool-call | Token reduction |
|---|---:|---:|---:|---:|
| Petstore | 19 | 100% | **95%** (k=5) | 64% |
| GitHub | 50 | 100% | **88%** (k=5) | 88% |
| Mixed MCP | 38 | 97% | **90%** (k=5) | 83% |
| Kubernetes core/v1 | 248 | **12%** | **82%** (k=5 + ontology) | 79% |

**Key finding** — at 248 tools, baseline collapses (context overflow) to 12% while graph-tool-call recovers to 82%. At smaller scales, baseline is already strong, so graph-tool-call's value is **token savings without accuracy loss**.

→ Full results (pipeline / retrieval-only / competitive / 1068-scale / 200-tool LangChain agent across GPT and Claude): **[docs/benchmarks.md](docs/benchmarks.md)**

```bash
# Reproduce
python -m benchmarks.run_benchmark                                # retrieval only
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b    # full pipeline
```

---

## Advanced

### Embedding-based hybrid search

Add semantic search on top of BM25 + graph. No heavy dependencies needed — connect to any external embedding server.

```python
tg.enable_embedding("ollama/qwen3-embedding:0.6b")        # Ollama (recommended)
tg.enable_embedding("openai/text-embedding-3-large")      # OpenAI
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")     # vLLM
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")  # local
tg.enable_embedding(lambda texts: my_embed_fn(texts))     # custom callable
```

Weights are auto-rebalanced. See [API reference](docs/api-reference.md#embedding-provider-strings) for all provider forms.

### Retrieval tuning

```python
tg.enable_reranker()                                      # cross-encoder rerank
tg.enable_diversity(lambda_=0.7)                          # MMR diversity
tg.set_weights(keyword=0.2, graph=0.5, embedding=0.3, annotation=0.2)
```

### History-aware retrieval

Pass previously called tools to demote them and boost next-step candidates.

```python
tools = tg.retrieve("now cancel it", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
```

### Save / load (preserves embeddings + weights)

```python
tg.save("my_graph.json")
tg = ToolGraph.load("my_graph.json")
# Or use cache= in from_url() for automatic save/load
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

### LLM-enhanced ontology

```python
tg.auto_organize(llm="ollama/qwen2.5:7b")
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")
tg.auto_organize(llm=openai.OpenAI())
```

Builds richer categories, relations, and search keywords. Supports Ollama, OpenAI clients, litellm, and any callable. See [API reference](docs/api-reference.md#ontology-llm-inputs).

### Other features

| Feature | API | Docs |
|---|---|---|
| Duplicate detection across specs | `find_duplicates` / `merge_duplicates` | [API ref](docs/api-reference.md#analysis) |
| Conflict detection | `apply_conflicts` | [API ref](docs/api-reference.md#analysis) |
| Operational analysis | `analyze` | [API ref](docs/api-reference.md#analysis) |
| Interactive dashboard | `dashboard()` | [API ref](docs/api-reference.md#export--visualization) |
| HTML / GraphML / Cypher export | `export_html` / `export_graphml` / `export_cypher` | [API ref](docs/api-reference.md#export--visualization) |
| Auto-fix bad OpenAPI specs | `from_url(url, lint=True)` | [ai-api-lint](https://github.com/SonAIengine/ai-api-lint) |

---

## Docs

| Doc | Description |
|---|---|
| [CLI reference](docs/cli.md) | All `graph-tool-call` CLI commands |
| [Python API reference](docs/api-reference.md) | `ToolGraph` methods, helpers, middleware, LangChain |
| [Integrations](docs/integrations/) | MCP server / proxy, LangChain, middleware, direct API |
| [Benchmark results](docs/benchmarks.md) | Full pipeline / retrieval / competitive / scale tables |
| [Architecture](docs/architecture/overview.md) | System overview, pipeline layers, data model |
| [Design notes](docs/design/) | Algorithm design — normalization, dependency detection, ontology |
| [Research](docs/research/) | Competitive analysis, API scale data |
| [Release checklist](docs/release-checklist.md) | Release process, changelog flow |

---

## Contributing

Contributions are welcome.

```bash
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev --all-extras

# Test, lint, benchmark
poetry run pytest -v
poetry run ruff check . && poetry run ruff format --check .
python -m benchmarks.run_benchmark -v
```

---

## License

[MIT](LICENSE)
