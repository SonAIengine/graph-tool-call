<div align="center">

# graph-tool-call

**Tool Lifecycle Management for LLM Agents**

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

**graph-tool-call** models tool relationships as a graph:

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

Instead of treating each tool as an independent vector, graph-tool-call understands:
- **REQUIRES** — `getOrder` needs an ID from `listOrders`
- **PRECEDES** — you must list orders before you can cancel one
- **COMPLEMENTARY** — cancellation and refund often go together
- **SIMILAR_TO** — `getOrder` and `listOrders` serve related purposes
- **CONFLICTS_WITH** — `updateOrder` and `deleteOrder` shouldn't run together

This means when you search for *"cancel order"*, you don't just get `cancelOrder` — you get the **complete workflow**: list → get → cancel → refund.

## How It Works

```
OpenAPI/MCP/Code → [Ingest] → [Analyze] → [Organize] → [Retrieve] → Agent
                    (convert)  (relations)  (graph)     (hybrid+rerank)
```

**1. Ingest** — Point it at a Swagger spec, MCP server, or Python functions. Tools are auto-converted into a unified schema. Optional [ai-api-lint](https://github.com/SonAIengine/ai-api-lint) integration auto-fixes poor OpenAPI specs before ingest.

**2. Analyze** — Relationships are automatically detected: path hierarchies, CRUD patterns, shared schemas, response→request data flow chains, state machines.

**3. Organize** — Tools are grouped into an ontology graph. Two modes:
  - **Auto** — purely algorithmic (tags, paths, CRUD patterns). No LLM needed.
  - **LLM-Auto** — enhanced with LLM reasoning. Better categories, richer relations, keyword enrichment. Pass any LLM — callable, OpenAI client, or string shorthand like `"ollama/qwen2.5:7b"`.

**4. Retrieve** — Multi-stage hybrid search pipeline:
  - **Stage 1**: wRRF fusion (BM25 + graph traversal + embedding + MCP annotation scoring)
  - **Stage 2**: Cross-encoder reranking (optional, for precision)
  - **Stage 3**: MMR diversity reranking (optional, reduces redundancy)
  - History-aware retrieval demotes already-used tools and augments graph seeds.

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

Copy-paste this to see it work immediately:

```python
from graph_tool_call import ToolGraph

# Build a tool graph from the official Petstore API
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",  # saves graph locally for instant reload
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# Search for tools
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

Add embedding-based semantic search on top of BM25 + graph. Supports multiple providers out of the box.

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

### Conflict Detection

Detect tools that shouldn't run together (e.g., `updateOrder` and `deleteOrder`):

```python
tg.apply_conflicts()
# Adds CONFLICTS_WITH edges between conflicting tool pairs
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

## 3-Tier Search: Use What You Have

graph-tool-call is designed to work **without any LLM** and get **better with one**:

| Tier | What you need | What it does | Improvement |
|------|--------------|--------------|-------------|
| **0** | Nothing | BM25 keywords + graph expansion + RRF fusion | Baseline |
| **1** | Small LLM (1.5B~3B) | + query expansion, synonyms, translation | Recall +15~25% |
| **2** | Full LLM (7B+) | + intent decomposition, iterative refinement | Recall +30~40% |

Even a tiny model running on Ollama (`qwen2.5:1.5b`) can meaningfully improve search quality. No GPU required for Tier 0.

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
```

## License

[MIT](LICENSE)
