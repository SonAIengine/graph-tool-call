# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned — Phase 3+
- Pyvis HTML graph visualization with progressive disclosure
- Neo4j Cypher / GraphML export
- CLI tool (`graph-tool-call ingest/retrieve/visualize`)
- Interactive Dashboard (Dash Cytoscape) — visualization + manual editing
- LangChain community package

## [0.4.0] - 2026-03-03

### Added
- **MCP Annotation-Aware Retrieval** — query intent와 tool annotation alignment 기반 retrieval signal
  - `MCPAnnotations` 모델: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`
  - `parse_mcp_tool()` + `parse_tool()` MCP format 자동 감지 (`inputSchema` key)
  - `ToolGraph.ingest_mcp_tools()` — MCP tool list ingest with server tagging
  - Intent Classifier (`classify_intent()`) — 한/영 키워드 기반 zero-LLM query intent 분류
  - Annotation Scorer (`score_annotation_match()`) — intent↔annotation alignment scoring
  - RetrievalEngine에 annotation score를 4번째 wRRF source로 통합 (weight=0.2)
  - OpenAPI ingest에서 HTTP method → MCP annotation 자동 추론 (RFC 7231 기반)
  - OntologyBuilder에 annotation 정보 node attribute 저장
  - Similarity Stage 3에 annotation 일치 보너스 (+0.1 max)
  - `MCPAnnotations` public export (`from graph_tool_call import MCPAnnotations`)
- **Tests**: 255개 (74개 신규)
  - `test_mcp_annotations.py`, `test_ingest_mcp.py`, `test_intent_classifier.py`
  - `test_annotation_scorer.py`, `test_annotation_retrieval.py`, `test_openapi_annotations.py`

## [0.3.0] - 2026-03-03

### Added
- **Deduplication**: 5-Stage duplicate detection pipeline
  - Stage 1: SHA256 exact hash
  - Stage 2: RapidFuzz name similarity (optional)
  - Stage 3: Parameter key Jaccard + type compatibility
  - Stage 4: Embedding cosine similarity (optional)
  - Stage 5: Composite weighted score
  - `find_duplicates()` / `merge_duplicates()` API with 3 strategies
- **Embedding Search**: sentence-transformers integration
  - `EmbeddingIndex` with `build_from_tools()` / `search()`
  - `tg.enable_embedding()` one-liner setup
  - Auto weight rebalancing (graph=0.5, keyword=0.2, embedding=0.3)
- **Ontology Modes**:
  - Auto mode: tag/path/CRUD/embedding clustering (no LLM)
  - LLM-Auto mode: Ollama/OpenAI provider, batch relation inference, category suggestion
  - `OntologyLLM` ABC + `OllamaLLM` / `OpenAILLM` providers
- **Search Tiers**: 3-Tier architecture (BASIC/ENHANCED/FULL)
  - Tier 1 (ENHANCED): query expansion via SearchLLM
  - Tier 2 (FULL): intent decomposition via SearchLLM
  - Weighted RRF (wRRF) for multi-source fusion
- **Arazzo 1.0.0**: workflow parser → PRECEDES relations
- **Layered Resilience**:
  - Description fallback: empty summary/description → `METHOD /path [tags]`
  - `ToolGraph.from_url()`: Swagger UI auto-discovery via swagger-config
  - `_discover_spec_urls()`: SpringDoc v1/v2 config, swagger-initializer.js parsing
- **BM25**: Korean bigram tokenization for compound words
- **Tests**: 181 tests passing (93 new)

### Changed
- Score fusion upgraded from RRF to wRRF (weighted Reciprocal Rank Fusion)
- Embedding fallback: when keyword+graph empty, embedding seeds graph expansion

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

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SonAIengine/graph-tool-call/releases/tag/v0.1.0
