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

## Quick Start

```bash
pip install graph-tool-call
```

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Register tools (OpenAI / Anthropic / LangChain format auto-detected)
tg.add_tools(your_tools_list)

# Define relationships
tg.add_relation("read_file", "write_file", "complementary")

# Retrieve — graph expansion finds related tools automatically
tools = tg.retrieve("read a file and save changes", top_k=5)
# → [read_file, write_file, list_dir, ...]
#    write_file found via COMPLEMENTARY relation, not just vector similarity
```

### From Swagger / OpenAPI

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
# Supports: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
# Accepts: file path (JSON/YAML), URL, or raw dict

# Automatic: 5 endpoints → 5 tools → CRUD relations → categories
# Dependencies, call ordering, category groupings — all auto-detected.

tools = tg.retrieve("create a new pet", top_k=5)
# → [createPet, getPet, updatePet, listPets, deletePet]
#    Graph expansion brings the full CRUD workflow
```

### From Swagger UI URL

```python
from graph_tool_call import ToolGraph

# Auto-discovers all API groups from Swagger UI
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# Also works with direct spec URLs
tg = ToolGraph.from_url("https://api.example.com/v3/api-docs")

# With ai-api-lint auto-fix + LLM ontology construction
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    lint=True,                    # auto-fix missing descriptions, error responses, etc.
    llm="ollama/qwen2.5:7b",     # LLM-enhanced categories + keyword enrichment
)

tools = tg.retrieve("search products", top_k=5)
```

`from_url()` automatically detects Swagger UI pages, discovers all spec groups via `swagger-config`, and ingests them into a single unified graph. Operations without descriptions get auto-generated fallbacks from their HTTP method, path, and tags.

### From MCP Server Tools

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Ingest MCP tool list (annotations are preserved)
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
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

# "delete files" → destructive tools ranked higher (annotation-aware)
tools = tg.retrieve("delete temporary files", top_k=5)
```

MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are used as retrieval signals. Query intent is automatically classified and aligned with tool annotations — read queries prefer read-only tools, delete queries prefer destructive tools.

### From Python Functions

```python
def read_file(path: str) -> str:
    """Read contents of a file."""

def write_file(path: str, content: str) -> None:
    """Write contents to a file."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# Parameters extracted from type hints, description from docstring
```

## Advanced Features

### Cross-Encoder Reranking

Second-stage reranking using a cross-encoder model for improved precision. The cross-encoder jointly encodes `(query, tool_description)` pairs — more accurate than independent embedding comparison.

```python
pip install graph-tool-call[embedding]
```

```python
tg.enable_reranker()  # default: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("cancel order", top_k=5)
# Results are first ranked by wRRF, then re-scored by cross-encoder
```

### MMR Diversity

Maximal Marginal Relevance reranking reduces redundant results. Useful when the top-k results contain many similar tools.

```python
tg.enable_diversity(lambda_=0.7)  # 0.7 = mostly relevant, some diversity
tools = tg.retrieve("manage orders", top_k=10)
```

### History-Aware Retrieval

Pass previously called tool names to improve retrieval context. Already-used tools are demoted, and their graph neighbors become seeds for expansion.

```python
# First call
tools = tg.retrieve("find my order")
# → [listOrders, getOrder, ...]

# Second call — history-aware
tools = tg.retrieve("now cancel it", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
#    listOrders/getOrder demoted, cancelOrder boosted via graph proximity
```

### LLM-Enhanced Ontology

Build richer tool ontologies using any LLM. The LLM infers categories, relations, and generates search keywords (especially useful for non-English tool descriptions).

```python
# Any of these work — auto-detected by wrap_llm()
tg.auto_organize(llm="ollama/qwen2.5:7b")           # string shorthand
tg.auto_organize(llm=lambda p: my_llm(p))            # callable
tg.auto_organize(llm=openai.OpenAI())                # OpenAI client
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")    # via litellm

# Or use build_ontology() after adding tools
tg.build_ontology(llm="ollama/qwen2.5:7b")
```

Supported LLM inputs:
| Input | Wrapped as |
|-------|-----------|
| `OntologyLLM` instance | Pass-through |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAI client (has `chat.completions`) | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completion wrapper |

### API Spec Lint Integration

Auto-fix poor OpenAPI specs before ingestion using [ai-api-lint](https://github.com/SonAIengine/ai-api-lint). Adds missing descriptions, error responses, schema enhancements, and more.

```bash
pip install graph-tool-call[lint]
```

```python
# Applied during from_url()
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/", lint=True)

# Or manually
from graph_tool_call.ingest.lint import lint_and_fix_spec
fixed_spec, result = lint_and_fix_spec(raw_spec, max_level=2)
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

## Installation Options

```bash
pip install graph-tool-call                    # core (BM25 + graph, no dependencies)
pip install graph-tool-call[embedding]         # + sentence-transformers, cross-encoder
pip install graph-tool-call[openapi]           # + YAML support for OpenAPI specs
pip install graph-tool-call[lint]              # + ai-api-lint spec auto-fix
pip install graph-tool-call[similarity]        # + rapidfuzz for deduplication
pip install graph-tool-call[visualization]     # + pyvis for HTML graph export
pip install graph-tool-call[langchain]         # + LangChain tool adapter
pip install graph-tool-call[all]               # everything
```

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

## Roadmap

| Phase | What | Status |
|-------|------|--------|
| **0** | Core graph engine + hybrid retrieval | ✅ Done |
| **1** | OpenAPI ingest, BM25+RRF retrieval, dependency detection | ✅ Done |
| **2** | Deduplication, embeddings, ontology modes (Auto/LLM-Auto), search tiers, `from_url()` | ✅ Done |
| **2.5** | MCP Annotation-Aware Retrieval: intent classifier, annotation scoring, wRRF integration | ✅ Done |
| **3** | Pyvis visualization, Neo4j export, CLI, PyPI publish | ✅ Done |
| **3.5** | Cross-encoder reranking, MMR diversity, history-aware retrieval, lint integration, LLM adapter | ✅ Done (318 tests) |
| **4** | Interactive dashboard, benchmarking, community | Planned |

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
```

## License

[MIT](LICENSE)
