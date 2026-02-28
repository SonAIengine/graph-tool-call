<div align="center">

# graph-tool-call

**Tool Lifecycle Management for LLM Agents**

Ingest, Analyze, Organize, Retrieve.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

English · [한국어](README-ko.md) · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

When your agent has hundreds or thousands of tools, loading all of them into the context window degrades performance. Existing solutions use vector similarity only. **graph-tool-call** models **relationships between tools** (dependencies, ordering, complements, conflicts) as a graph, enabling structure-aware retrieval.

```
OpenAPI/MCP/Code → [Ingest] → [Analyze] → [Organize] → [Retrieve] → Agent
                    (convert)  (relations)  (graph)     (hybrid)
```

## Why graph-tool-call?

| Feature | Vector-only solutions | graph-tool-call |
|--|---|---|
| Scope | Tool retrieval only | Full tool lifecycle |
| Tool source | Manual registration | Auto-ingest from Swagger/OpenAPI |
| Search | Flat vector similarity | Graph + vector hybrid (RRF), 3-Tier |
| Relations | None | REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH |
| Deduplication | None | Cross-source duplicate detection |
| Dependency | None | Auto-detected from API specs |
| Call ordering | None | State machine + CRUD workflow detection |
| Ontology | None | Auto / LLM-Auto modes |

## Quick Start

### Installation

```bash
pip install graph-tool-call
```

### Basic Usage

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Register tools (OpenAI / Anthropic / LangChain format auto-detected)
tg.add_tools(your_tools_list)

# Organize with categories and relations
tg.add_category("file_ops", domain="io")
tg.assign_category("read_file", "file_ops")
tg.add_relation("read_file", "write_file", "complementary")

# Retrieve relevant tools for a query
tools = tg.retrieve("read a file and save changes", top_k=5)
```

### OpenAPI Ingest (Phase 1)

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# Auto-discovers: CRUD dependencies, call ordering, category groupings
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
```

## Key Features

### Ingest
Auto-convert tools from OpenAPI/Swagger, MCP servers, Python functions, and LangChain/OpenAI/Anthropic formats into a unified schema. Spec normalization handles Swagger 2.0, OpenAPI 3.0, and 3.1 transparently.

### Analyze
Automatically detect relationships between tools:
- **REQUIRES** — data dependency (response → parameter)
- **PRECEDES** — call ordering (list → cancel)
- **COMPLEMENTARY** — useful together (read ↔ write)
- **SIMILAR_TO** — overlapping functionality
- **CONFLICTS_WITH** — mutually exclusive operations

### Organize
Build an ontology graph with two modes:
- **Auto** — algorithmic categorization (tags, paths, CRUD patterns, embedding clustering). No LLM needed.
- **LLM-Auto** — Auto + LLM-enhanced relation inference and category suggestions (Ollama, vLLM, llama.cpp, OpenAI).

Results can be visualized and manually edited via the Dashboard.

### Retrieve
3-Tier hybrid search architecture:
| Tier | LLM Required | Method |
|------|-------------|--------|
| 0 | No | BM25 + graph expansion + RRF |
| 1 | Small (1.5B~3B) | + query expansion |
| 2 | Full (7B+) | + intent decomposition |

Works without LLM. Better with one.

## Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| **0** | Core graph + retrieval | ✅ Done (32 tests) |
| **1** | OpenAPI ingest + dependency/ordering detection | In progress |
| **2** | Dedup + embedding + ontology modes + search modes | Planned |
| **3** | MCP ingest + visualization + CLI + PyPI | Planned |
| **4** | Interactive dashboard + community | Planned |

## Documentation

- [WBS](docs/wbs/) — Work Breakdown Structure
- [Architecture](docs/architecture/overview.md) — System overview and data model
- [Design](docs/design/) — Algorithm design docs
- [Research](docs/research/) — Competitive analysis, API scale data

## Contributing

Contributions are welcome! Please read our contributing guidelines (coming soon).

```bash
# Development setup
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev
poetry run pytest -v
```

## License

[MIT](LICENSE)
