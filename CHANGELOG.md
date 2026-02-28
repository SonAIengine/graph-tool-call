# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.2.0] - 2026-03-01

### Added
- **Ingest**: OpenAPI/Swagger spec auto-ingest (`tg.ingest_openapi()`)
  - Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1 support
  - Spec normalization layer (`SpecVersion`, `NormalizedSpec`)
  - `$ref` resolution with circular reference detection
  - Auto-generated `operationId` for unnamed operations
  - `required_only` and `skip_deprecated` options
  - YAML support via optional `pyyaml` dependency
- **Ingest**: Python callable ingest (`tg.ingest_functions()`)
  - `inspect.signature` + type hints + docstring parsing
- **Analyze**: Automatic dependency detection (`detect_dependencies()`)
  - Layer 1 (Structural): path hierarchy, CRUD patterns, shared `$ref` schemas
  - Layer 2 (Name-based): response→parameter name matching
  - Confidence scoring (0.0~1.0) with configurable threshold
  - False positive prevention (generic param filtering, deduplication)
- **Ontology**: `PRECEDES` relation type for workflow ordering (weight 0.9)
  - CRUD lifecycle ordering: POST → GET → PUT → DELETE
- **Retrieval**: BM25 keyword scoring (`BM25Scorer`)
  - Improved tokenizer: camelCase/snake_case/kebab-case splitting
  - Tool-specific document creation (name + description + tags + params)
- **Retrieval**: Reciprocal Rank Fusion (RRF) replacing weighted sum
- **Retrieval**: `SearchMode` enum (BASIC/ENHANCED/FULL) — 3-Tier architecture
- **Tests**: 88 tests passing (49 new tests + fixtures)
  - `test_normalizer.py` (10), `test_ingest_openapi.py` (12), `test_ingest_functions.py` (6)
  - `test_dependency.py` (10), `test_bm25.py` (7), `test_e2e_phase1.py` (11)
  - Fixtures: `petstore_swagger2.json`, `minimal_openapi30.json`, `minimal_openapi31.json`

### Fixed
- Tags processing `TypeError` in `retrieval/engine.py` — `set.update()` was receiving a generator of lists instead of flat tokens

### Changed
- Keyword scoring upgraded from simple token overlap to BM25
- Score fusion upgraded from hardcoded weighted sum to RRF (k=60)
- `retrieve()` now accepts optional `mode` parameter (default `SearchMode.BASIC`)

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

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SonAIengine/graph-tool-call/releases/tag/v0.1.0
