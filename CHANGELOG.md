# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned — Phase 1
- OpenAPI/Swagger spec ingest with auto-dependency detection
- Spec normalization layer (Swagger 2.0 / OpenAPI 3.0 / 3.1)
- `PRECEDES` relation type for API call ordering detection
- State machine detection from enum status fields
- CRUD workflow ordering
- BM25-style keyword scoring + RRF score fusion
- `SearchMode` enum (BASIC/ENHANCED/FULL) — 3-Tier search architecture
- Model-Driven Search API skeleton
- Python callable → ToolSchema conversion
- OpenAPI spec writing guide for better ontology detection

### Planned — Phase 2
- 5-stage deduplication pipeline
- Embedding search (all-MiniLM-L6-v2 / multilingual-e5)
- Ontology modes: Auto (no LLM) / LLM-Auto (Ollama/vLLM/OpenAI)
- Search Tier 1 (query expansion) and Tier 2 (intent decomposition)
- Arazzo Specification support for workflow parsing

### Planned — Phase 3
- MCP server tool ingest
- Pyvis HTML graph visualization with progressive disclosure
- Neo4j Cypher / GraphML export
- CLI tool (`graph-tool-call ingest/retrieve/visualize`)
- Commerce domain presets (order/payment/shipping workflows)
- PyPI distribution

### Planned — Phase 4
- Interactive Dashboard (Dash Cytoscape) — visualization + manual editing
- LangChain community package

## [0.1.0] - 2026-03-01

### Added
- **Core**: `ToolSchema` unified data model with OpenAI, Anthropic, LangChain format parsers
- **Graph**: NetworkX-based `GraphEngine` with BFS traversal and serialization
- **Ontology**: Domain → Category → Tool hierarchy with 5 relation types
  - REQUIRES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH, BELONGS_TO
- **Retrieval**: Hybrid keyword + graph expansion scoring engine
- **Integration**: LangChain `BaseRetriever` adapter
- **Serialization**: JSON save/load roundtrip for full graph state
- **Docs**: Project plan (PLAN.md), research notes (RESEARCH.md), WBS structure
- **Tests**: 32 tests passing across all modules
- **Example**: `quickstart.py` demonstrating full workflow

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SonAIengine/graph-tool-call/releases/tag/v0.1.0
