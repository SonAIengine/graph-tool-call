<div align="center">

# graph-tool-call

**Graph-based Tool Retrieval for LLM Agents**

Ingest, Analyze, Organize, Retrieve.

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

English · [한국어](README-ko.md) · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

## The Problem

LLM agents are getting access to more and more tools. A commerce platform might expose **1,200+ API endpoints**. A company's internal toolset might have **500+ functions** across multiple services.

But there's a hard limit: **you can't put them all in the context window.**

The common solution? Vector search — embed tool descriptions, find the closest matches. It works, but it misses something important:

> **Tools don't exist in isolation. They have relationships.**

When a user says *"cancel my order and process a refund"*, vector search might find `cancelOrder`. But it won't know that you need to call `listOrders` first (to get the order ID), and that `processRefund` should follow. These aren't just similar tools — they form a **workflow**.

## The Solution

**graph-tool-call** models tool relationships as a graph and retrieves tools using a multi-signal hybrid search pipeline:

```
OpenAPI/MCP/Code → [Ingest] → [Analyze] → [Organize] → [Retrieve] → Agent
                    (convert)  (relations)  (graph)     (wRRF hybrid)
```

**4-source wRRF fusion**: BM25 keyword matching + graph traversal + embedding similarity + MCP annotation scoring — combined via weighted Reciprocal Rank Fusion.

```
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

## Benchmark

> **Can the LLM pick the right tool?**
> We gave an LLM a user request and tool definitions, then checked if it called the correct tool.
> - **Without** graph-tool-call: pass **all** tool definitions to the LLM.
> - **With** graph-tool-call: pass only the **top-5 retrieved** tools.

All benchmarks use public specs anyone can download and reproduce: [Petstore OpenAPI](https://petstore3.swagger.io), [Kubernetes core/v1 API](https://github.com/kubernetes/kubernetes), GitHub REST API, and MCP tool servers.

### Result: Does graph-tool-call help the LLM?

Model: qwen3.5:4b (4-bit quantized, Ollama). Each query asks the LLM to call the right tool.

| API | Total tools | Without graph-tool-call | With graph-tool-call | What changed |
|-----|:----------:|:----------------------:|:-------------------:|:-------------|
| Petstore | 19 | 60% accuracy | **75% accuracy** | **+15pp better**, 70% fewer tokens |
| GitHub | 50 | 20% accuracy | 20% accuracy | Same accuracy, **60% fewer tokens** |
| **Kubernetes** | **248** | **Cannot run** | **60% accuracy** | 248 tools = 100K tokens. No small model can fit them. **Only works with retrieval.** |

The takeaway: as the number of tools grows, passing them all to the LLM breaks down. At **248 tools**, the model can't even receive them — graph-tool-call makes it possible by filtering to just 5 relevant tools.

### How good is the retrieval?

Before the LLM sees anything, graph-tool-call must first **find** the right tools. We measure this with **Recall@K**: *"Is the correct tool in the top-K results?"*

| API | Total tools | Recall@3 | Recall@5 | Recall@10 |
|-----|:----------:|:--------:|:--------:|:---------:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub REST | 50 | 77.5% | **85.0%** | 87.5% |
| MCP (filesystem + GitHub) | 38 | 90.0% | **96.7%** | 100.0% |
| Kubernetes | 248 | 60.0% | **64.0%** | 72.0% |

With 19 tools, the correct tool is in the top-5 **98% of the time**. Even at 248 tools, **Recall@10 reaches 72%** — and this is without any embedding model, using only BM25 + graph traversal.

<details>
<summary>Detailed breakdown by operation type</summary>

**Petstore** (19 tools) — Recall@5

| Operation | Recall | Queries |
|-----------|:------:|:-------:|
| read | 100.0% | 8 |
| write | 100.0% | 8 |
| delete | 100.0% | 3 |
| workflow (multi-tool) | 66.7% | 1 |

**GitHub** (50 tools) — Recall@5

| Operation | Recall | Queries |
|-----------|:------:|:-------:|
| write | 94.1% | 17 |
| read | 80.0% | 20 |
| delete | 66.7% | 3 |

**Kubernetes** (248 tools) — Recall@5

| Operation | Recall | Queries |
|-----------|:------:|:-------:|
| write | 80.0% | 15 |
| delete | 75.0% | 8 |
| read | 51.9% | 27 |

</details>

### When does embedding help?

We tested adding an embedding model ([nomic-embed-text](https://ollama.com/library/nomic-embed-text), Ollama) on top of BM25 + graph. The result depends on the number of tools:

| API | Tools | BM25 + Graph | + Embedding | Improved | Degraded |
|-----|:-----:|:------------:|:-----------:|:--------:|:--------:|
| Petstore | 19 | 98.3% | 98.3% | 0 | 0 |
| GitHub | 58 | 85.0% | 77.5% | 0 | 3 |
| MCP | 38 | 96.7% | 90.0% | 0 | 2 |
| **Kubernetes** | **248** | **64.0%** | **66.0%** | **1** | **0** |

**The pattern**: For small/medium tool sets (< 100), BM25 keyword matching is already precise enough — adding embedding introduces noise and can push correct tools out of top-5. But for **large tool sets (248+)**, where many tools share similar names (`readCoreV1NamespacedPodStatus` vs `connectCoreV1GetNamespacedPodAttach`), embedding provides the semantic understanding that BM25 alone can't.

**Recommendation**: Enable embedding when your tool count exceeds ~100. For smaller sets, BM25 + graph is sufficient.

### Reproduce it

```bash
# Retrieval quality (fast, no LLM needed)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v          # Kubernetes 248 tools

# End-to-end with LLM
python -m benchmarks.run_benchmark --mode e2e -m qwen3:4b

# Embedding comparison
python -m benchmarks.run_embedding_benchmark --embedding "ollama/nomic-embed-text"
```

## Installation

```bash
pip install graph-tool-call                    # core (BM25 + graph)
pip install graph-tool-call[embedding]         # + embedding, cross-encoder reranker
pip install graph-tool-call[openapi]           # + YAML support for OpenAPI specs
pip install graph-tool-call[all]               # everything
```

<details>
<summary>All extras</summary>

```bash
pip install graph-tool-call[lint]              # + ai-api-lint spec auto-fix
pip install graph-tool-call[similarity]        # + rapidfuzz for deduplication
pip install graph-tool-call[visualization]     # + pyvis for HTML graph export
pip install graph-tool-call[langchain]         # + LangChain tool adapter
```

</details>

## Quick Start

### 30-Second Example

```python
from graph_tool_call import ToolGraph

# Build a tool graph from the official Petstore API
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",  # saves graph locally for instant reload
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# Search for tools — 98.3% Recall@5 on this spec
tools = tg.retrieve("create a new pet", top_k=5)
for t in tools:
    print(f"  {t.name}: {t.description}")
# → addPet: Add a new pet to the store.
#   updatePet: Update an existing pet.
#   getPetById: Find pet by ID.
#   ...graph expansion brings the full CRUD workflow
```

### From Your Own Swagger / OpenAPI

```python
from graph_tool_call import ToolGraph

# From file (JSON or YAML)
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# From URL — auto-discovers all spec groups from Swagger UI
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# With caching — build once, reload instantly
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",  # first call: fetch + build + save
)                          # next calls: load from file (no network)

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

# Annotation-aware: "delete files" → destructive tools ranked higher
tools = tg.retrieve("delete temporary files", top_k=5)
```

MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are used as retrieval signals. Query intent is automatically classified and aligned with tool annotations.

### From Python Functions

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """Read contents of a file."""

def write_file(path: str, content: str) -> None:
    """Write contents to a file."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# Parameters extracted from type hints, description from docstring
```

### Manual Tool Registration

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# OpenAI function-calling format — auto-detected
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

# Define relationships manually
tg.add_relation("get_weather", "get_forecast", "complementary")
```

## Embedding (Hybrid Search)

Add embedding-based semantic search on top of BM25 + graph. Any OpenAI-compatible endpoint works.

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers (local, no API key needed)
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / any OpenAI-compatible server
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")  # URL@model format

# Custom callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

Weights are automatically rebalanced when embedding is enabled. You can fine-tune them:

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

## Save & Load

Build once, reuse everywhere. The full graph structure (nodes, edges, relation types, weights) is preserved.

```python
# Save
tg.save("my_graph.json")

# Load
tg = ToolGraph.load("my_graph.json")

# Or use cache= in from_url() for automatic save/load
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

## Advanced Features

### Cross-Encoder Reranking

Second-stage reranking using a cross-encoder model. Jointly encodes `(query, tool_description)` pairs for more accurate scoring than independent embedding comparison.

```python
tg.enable_reranker()  # default: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("cancel order", top_k=5)
# Results are first ranked by wRRF, then re-scored by cross-encoder
```

### MMR Diversity

Maximal Marginal Relevance reranking reduces redundant results.

```python
tg.enable_diversity(lambda_=0.7)  # 0.7 = mostly relevant, some diversity
```

### History-Aware Retrieval

Pass previously called tool names to improve context. Already-used tools are demoted, and their graph neighbors become seeds for expansion.

```python
# First call
tools = tg.retrieve("find my order")
# → [listOrders, getOrder, ...]

# Second call — history-aware
tools = tg.retrieve("now cancel it", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
#    listOrders/getOrder demoted, cancelOrder boosted via graph proximity
```

### wRRF Weight Tuning

Fine-tune the weighted Reciprocal Rank Fusion weights for each scoring source:

```python
tg.set_weights(
    keyword=0.2,     # BM25 text matching
    graph=0.5,       # graph traversal (relation-based)
    embedding=0.3,   # semantic similarity
    annotation=0.2,  # MCP annotation matching
)
```

### LLM-Enhanced Ontology

Build richer tool ontologies using any LLM. The LLM infers categories, relations, and generates search keywords (especially useful for non-English tool descriptions).

```python
# Any of these work — auto-detected by wrap_llm()
tg.auto_organize(llm="ollama/qwen2.5:7b")           # string shorthand
tg.auto_organize(llm=lambda p: my_llm(p))            # callable
tg.auto_organize(llm=openai.OpenAI())                # OpenAI client
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")    # via litellm
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

Find and merge duplicate tools across multiple API specs:

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### Export & Visualization

```python
# Interactive HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (for Gephi, yEd)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint Integration

Auto-fix poor OpenAPI specs before ingestion using [ai-api-lint](https://github.com/SonAIengine/ai-api-lint):

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)  # auto-fix during ingest
```

## Why Not Just Vector Search?

| Scenario | Vector-only | graph-tool-call |
|----------|------------|-----------------|
| *"cancel my order"* | Returns `cancelOrder` | Returns `listOrders → getOrder → cancelOrder → processRefund` (full workflow) |
| *"read and save file"* | Returns `read_file` | Returns `read_file` + `write_file` (via COMPLEMENTARY) |
| *"delete old records"* | Returns any tool matching "delete" | Destructive tools ranked first (annotation-aware) |
| *"now cancel it"* (with history) | No context, same results | Demotes used tools, boosts next-step tools |
| Multiple Swagger specs with overlapping tools | Duplicate tools in results | Auto-deduplication across sources |
| 1,200 API endpoints | Slow, noisy results | Organized into categories, precise graph traversal |

## Full API Reference

<details>
<summary>ToolGraph methods</summary>

| Method | Description |
|--------|-------------|
| `add_tool(tool)` | Add a single tool (auto-detects format) |
| `add_tools(tools)` | Add multiple tools |
| `ingest_openapi(source)` | Ingest from OpenAPI/Swagger spec |
| `ingest_mcp_tools(tools)` | Ingest from MCP tool list |
| `ingest_functions(fns)` | Ingest from Python callables |
| `ingest_arazzo(source)` | Ingest Arazzo 1.0.0 workflow spec |
| `from_url(url, cache=...)` | Build from Swagger UI or spec URL |
| `add_relation(src, tgt, type)` | Add a manual relation |
| `auto_organize(llm=...)` | Auto-categorize tools |
| `build_ontology(llm=...)` | Build complete ontology |
| `retrieve(query, top_k=10)` | Search for tools |
| `enable_embedding(provider)` | Enable hybrid embedding search |
| `enable_reranker(model)` | Enable cross-encoder reranking |
| `enable_diversity(lambda_)` | Enable MMR diversity |
| `set_weights(...)` | Tune wRRF fusion weights |
| `find_duplicates(threshold)` | Find duplicate tools |
| `merge_duplicates(pairs)` | Merge detected duplicates |
| `apply_conflicts()` | Detect and add CONFLICTS_WITH edges |
| `save(path)` / `load(path)` | Serialize / deserialize graph |
| `export_html(path)` | Export interactive HTML visualization |
| `export_graphml(path)` | Export to GraphML format |
| `export_cypher(path)` | Export as Neo4j Cypher statements |

</details>

## Feature Comparison

| Feature | Vector-only solutions | graph-tool-call |
|---------|----------------------|-----------------|
| Tool source | Manual registration | Auto-ingest from Swagger/OpenAPI/MCP |
| Search method | Flat vector similarity | Multi-stage hybrid (wRRF + rerank + MMR) |
| Behavioral semantics | None | MCP annotation-aware retrieval |
| Tool relations | None | 6 relation types, auto-detected |
| Call ordering | None | State machine + CRUD + response→request data flow |
| Deduplication | None | Cross-source duplicate detection |
| Ontology | None | Auto / LLM-Auto modes (any LLM) |
| History awareness | None | Demotes used tools, boosts next-step |
| Spec quality | Assumes good specs | ai-api-lint auto-fix integration |
| LLM dependency | Required | Optional (better with, works without) |

## Documentation

| Doc | Description |
|-----|-------------|
| [Architecture](docs/architecture/overview.md) | System overview, pipeline layers, data model |
| [WBS](docs/wbs/) | Work Breakdown Structure — Phase 0~4 progress |
| [Design](docs/design/) | Algorithm design — spec normalization, dependency detection, search modes, call ordering, ontology modes |
| [Research](docs/research/) | Competitive analysis, API scale data, commerce patterns |
| [OpenAPI Guide](docs/design/openapi-guide.md) | How to write API specs that produce better tool graphs |

## Contributing

Contributions are welcome!

```bash
# Development setup
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev

# Run tests
poetry run pytest -v

# Lint
poetry run ruff check .
poetry run ruff format --check .

# Run benchmarks
python -m benchmarks.run_benchmark -v
```

## License

[MIT](LICENSE)
