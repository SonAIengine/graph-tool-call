# graph-tool-call

**Tool Lifecycle Management for LLM Agents** — Ingest, Analyze, Organize, Retrieve.

When your agent has hundreds or thousands of tools, loading all of them into the context window degrades performance. Existing solutions use vector similarity only. **graph-tool-call** goes further: it models **relationships between tools** (dependencies, ordering, complements, conflicts) as a graph, enabling structure-aware retrieval.

```
OpenAPI/MCP/Code → [Ingest] → [Analyze] → [Organize] → [Retrieve] → Agent
                    (convert)  (relations)  (graph)     (hybrid)
```

## Key Differentiators

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

## Swagger → Tool Graph (coming in Phase 1)

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# Auto-discovers: CRUD dependencies, category groupings, resource relations
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
```

## Status

**Phase 0 MVP** (core graph + retrieval) is implemented and tested (32 tests passing). Phase 1 (OpenAPI ingest + dependency detection) is next.

## Documentation

- [WBS](docs/wbs/) — Work Breakdown Structure (Phase 0-4 진행 상황)
- [Architecture](docs/architecture/overview.md) — System overview and data model
- [Design](docs/design/) — Algorithm design docs (spec normalization, dependency detection, retrieval)
- [Research](docs/research/) — Competitive analysis, API scale data, framework comparison

## Installation

```bash
pip install graph-tool-call
```

## License

MIT
