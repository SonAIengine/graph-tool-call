# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.19.0] - 2026-03-24

### Added
- **`ToolGraph.as_tools()`** — LangChain/LangGraph 완벽 호환 gateway 메서드
  - `search_tools` + `call_tool` 2개 메타툴 생성 (MCP 라우터 패턴)
  - 그래프 기반 BM25+관계 검색으로 관련 도구 탐색
  - 등록된 도구의 원본 callable 직접 실행
  - `as_tools()` 이후 추가된 도구도 라이브 참조로 즉시 반영
- **`ToolGraph.__iter__()` / `__len__()`** — Sequence 프로토콜 지원
  - `tools=tg` 구문으로 LangChain agent에 직접 전달 가능
  - `create_react_agent(model=llm, tools=tg)` 패턴 지원

## [0.18.0] - 2026-03-23

### Added
- **`create_agent()` query_mode="llm"** — LLM 기반 검색 쿼리 생성 모드 추가
  - 대화 컨텍스트 전체를 분석해 tool 검색 쿼리 자동 생성
  - 멀티턴 대화에서 "그거 취소해줘" 같은 대명사/맥락 의존 표현 해결
  - `query_model` 파라미터로 쿼리 생성 전용 경량 모델 지정 가능 (비용 절감)
  - 기본값 `query_mode="message"`는 기존과 동일 (추가 LLM 호출 없음)

### Changed
- `create_agent()` 시그니처 확장: `query_mode`, `query_model` 파라미터 추가

## [0.13.0] - 2026-03-15

### Added
- **워크플로우 가이드** — 검색 결과에 tool 간 관계 + 실행 순서 자동 포함
  - `ToolRelation(target, type, direction, hint)`: REQUIRES, PRECEDES, COMPLEMENTARY 관계
  - `prerequisites`: 결과에 없지만 선행 필요한 tool 목록
  - `workflow.suggested_order`: 토폴로지 정렬 기반 실행 순서 추천
  - MCP server/proxy 검색 결과에 자동 포함 (~100 토큰 추가)
- **세션 이력 기반 재검색** — MCP server/proxy에서 호출 이력 자동 추적
  - 이미 호출한 tool은 0.8x 감점 → 재검색 시 새 후보가 올라옴
  - `search_tools` → `execute_tool` → 다시 `search_tools` 시 자동 반영

### Changed
- **자동 관계 감지 정확도 개선** — 워크플로우 정확도 0/5 → 3/5
  - CRUD ordering 정밀화: POST→GET→PUT/PATCH→DELETE 순서 명시적 추론
  - name-based detection 방향 수정 + creator(POST) tool만 REQUIRES 대상
  - GET→PUT/DELETE PRECEDES 추가 (조회 후 수정/삭제 패턴)
- **온톨로지 역할 재정의** — 관계/워크플로우에만 집중, 키워드 enrichment 제거
  - keyword enrichment 제거: BM25 IDF 오염 방지 (Top-1 75% 유지)
  - example_queries 생성 제거: LLM이 query 시점에 처리
  - LLM 호출 4회 → 2회 (관계+카테고리만), 비용 50% 절감

### Fixed
- **embedding rebuild 순서 버그** — `auto_organize()` 후 embedding이 소실되던 critical bug 수정
- **워크플로우 방향 반전 버그** — incoming PRECEDES가 outgoing으로 해석되던 문제 수정
- **BM25에 example_queries 인덱싱** 추가 (LLM 생성 예시가 검색에 반영)

### Benchmark

| 지표 | v0.12.1 | v0.13.0 |
|------|---------|---------|
| Top-1 (ecommerce) | 75% | **75%** (온톨로지 후에도 유지) |
| Top-5 (ecommerce) | 90% | **90%** |
| 워크플로우 정확도 | 미지원 | **3/5** |
| iterative Top-1 (history) | — | **95%+** |
| 온톨로지 LLM 호출 | 4회 | **2회** |

## [0.12.1] - 2026-03-15

### Changed
- **Top-1 정확도 25% 향상** — wRRF fusion 후 3단계 post-processing 추가
  - Name-query overlap boost: tool name과 쿼리 토큰의 직접 매칭 시 가산
  - HTTP method-intent alignment: 쿼리 의도(생성/조회/삭제)와 HTTP method 대조
  - Description-only embedding rerank: Top-10 후보의 description만 batch encode (1회 API 호출)로 재정렬
  - Ecommerce 20쿼리: Top-1 **60% → 75%**, Top-5 90% 유지
  - GitHub 1,062 tools: Top-1 **60% → 70%**, Top-5 90% 유지

## [0.12.0] - 2026-03-15

### Added
- **HTTP Execution 파이프라인** — OpenAPI 검색 → 실제 API 호출까지 end-to-end
  - `ToolGraph.execute(tool_name, args, base_url=...)` — 검색 결과로 바로 HTTP 호출
  - `ToolGraph.dry_run(tool_name, args, ...)` — request 미리보기 (디버깅용)
  - CLI `graph-tool-call call "query" --source spec.json --base-url https://...`
  - MCP server `execute_tool` — LLM이 search → schema → execute 자동 연결
  - path/query/body 파라미터 자동 분류, Bearer 인증 지원
  - `--dry-run` 모드로 실행 전 request 확인 가능
  - zero-dependency (`urllib.request`만 사용)
- **CLI `search` 개선**
  - `--embedding` 옵션: `graph-tool-call search "query" --source spec.json --embedding ollama/...`
  - `--cache` 옵션: 반복 검색 시 그래프 재빌드 생략 (첫 실행 16s → 캐시 2s)

### Changed
- **Embedding 검색 3000x 속도 향상** — per-item loop → pre-computed matrix matmul
  - 1,062 tool 기준: cosine search **300ms → 0.1ms**
  - `EmbeddingIndex`: normalized matrix + `np.argpartition` 사용
  - 첫 검색 시 1회 matrix 빌드 후 캐시 (dirty flag)
- **BM25 정확도 향상** (대규모 spec에서 Top-5 +10%)
  - Name-length penalty: 긴 operationId의 부분 매칭 노이즈 억제
  - Subsequence boost: 쿼리 토큰이 tool name에 순서대로 매칭 시 최대 1.5x 가산
  - tf_map pre-computation: score() 호출마다 반복하던 TF 계산을 빌드 시 1회로
- **wRRF 기본 weight 재조정** — keyword 0.3→0.5, graph 0.7→0.5 (BM25 신뢰도 ↑)

### Benchmark (GitHub API — 1,062 tools, 43 categories)

| 지표 | v0.11.1 | v0.12.0 |
|------|---------|---------|
| BM25 Top-5 Recall | 80% | **90%** |
| BM25+Embedding Top-5 | 90% | **90%** |
| Embedding search latency | ~300ms | **0.1ms** |
| CLI 반복 검색 (cache) | 16s | **2s** |

### Benchmark (Ecommerce — 46 tools, 한글+영문 20쿼리)

| 지표 | v0.11.1 | v0.12.0 |
|------|---------|---------|
| BM25+Embedding Top-5 | 90% | **90%** |
| BM25+Embedding Top-1 | — | **60%** |

## [0.11.1] - 2026-03-14

### Changed
- **MCP Proxy gateway 전면 개선**
  - 1-hop direct calling: search 후 매칭 tool이 `tools/list`에 자동 등록 → 직접 호출
  - `search_tools`: inputSchema 제거, score/confidence 포함, description 120자 축약
  - `get_tool_schema`: on-demand full schema 조회
  - Direct backend routing + `call_backend_tool` fallback 유지
- **Graph 캐싱** — `cache_path` 옵션, 재시작 시 embedding 재계산 생략 (fingerprint 무효화)
- **Embedding provider 문자열 지정** — `"ollama/qwen3-embedding:0.6b"` 형식 지원
- **embedding extra 경량화** — `[embedding]` = numpy만, `[embedding-local]` = sentence-transformers

## [0.11.0] - 2026-03-14

### Changed
- **Zero-dependency core** — pydantic, networkx 필수 의존성 완전 제거
  - `pydantic.BaseModel` → `dataclasses.dataclass` 마이그레이션 (ToolSchema, ToolParameter, MCPAnnotations, NormalizedSpec)
  - `networkx.DiGraph` → 경량 `DictGraph` 자체 구현 (~150줄, 순수 Python dict 기반)
  - `model_dump()` 호환 shim 유지 → 기존 코드 100% 호환
  - `NetworkXGraph`는 `[visualization]` extra로 이동 (GraphML export용)
  - `ToolSchema(**dict)` 역직렬화: `__post_init__`에서 nested dict → dataclass 자동 변환
- **Lazy import 전면 적용** — `import graph_tool_call` 시 외부 모듈 로드 505개 → 26개 (95% 감소)
  - `__init__.py`: analyze/assist 심볼 `__getattr__` lazy
  - `analyze/`, `assist/`, `dashboard/`, `langchain/`, `ontology/` 서브패키지 lazy
  - `tool_graph.py`: retrieval/serialization/net 사용 시점 import
- **extras 재정리**
  - `visualization = ["pyvis", "networkx"]` — networkx는 GraphML export에만 필요
  - `all` extra에 networkx 포함

## [0.10.1] - 2026-03-14

### Changed
- **MCP Proxy gateway 모드** — `tools/list`에 2개 meta-tool만 노출 (99.9% 토큰 절감)
  - `search_tools` + `call_backend_tool` 2-hop 패턴으로 context 최소화
  - 적응형 모드: tool ≤ 30개 → passthrough, > 30개 → gateway 자동 전환
  - `--embedding` 옵션: cross-language embedding 검색 지원
  - `--passthrough-threshold` 옵션: 모드 전환 기준값 설정
  - search 결과에 inputSchema 포함 → LLM이 바로 인자 구성 가능
  - zero-result fallback: 검색 0건 시 빈 filter 대신 안내 메시지 반환

## [0.10.0] - 2026-03-14

### Added
- **MCP Proxy mode** — aggregate multiple MCP servers, filter tools via ToolGraph
  - `graph-tool-call proxy --config backends.json` — sits between client and backend servers
  - Collects tools from all backends, builds ToolGraph, exposes filtered subset
  - `search_tools` meta-tool: LLM searches → tool list dynamically filtered
  - `reset_tool_filter` meta-tool: restore full tool list
  - `tools/list_changed` notification: client auto-refreshes after filter change
  - Tool name collision handling: auto-prefixes with backend name
  - Config supports native format and `.mcp.json` format
  - Graceful backend failure: if one backend fails, others still work

## [0.9.0] - 2026-03-13

### Added
- **MCP server mode** — run graph-tool-call as an MCP tool provider
  - `graph-tool-call serve --source <url>` — stdio transport for Claude Code, Cursor, etc.
  - 5 MCP tools: `search_tools`, `get_tool_schema`, `list_categories`, `graph_info`, `load_source`
  - `create_mcp_server()` / `run_server()` programmatic API
  - `[mcp]` optional extra (`pip install graph-tool-call[mcp]`)
- **`search` CLI command** — one-liner ingest + retrieve
  - `graph-tool-call search "query" --source <url>` — no pre-build step needed
  - `--scores` for detailed relevance scores, `--json` for pipeline-friendly output
  - Works with `uvx graph-tool-call search ...` for zero-install experience
- **SDK middleware** for OpenAI and Anthropic clients
  - `patch_openai(client, graph=tg)` / `patch_anthropic(client, graph=tg)`
  - Automatically filters tool list based on user message before each API call
  - `unpatch_openai()` / `unpatch_anthropic()` to restore original behavior
  - Configurable `top_k` and `min_tools` thresholds

### Changed
- `_check_mcp_installed()` raises `ImportError` instead of `sys.exit(1)` for testability
- CI: fixed ruff format issues in existing files, added `pytest.importorskip("numpy")` for embedding tests

## [0.8.0] - 2026-03-12

### Planned — Phase 4
- Interactive dashboard manual editing and relation review workflow
- LangChain community package
- llama.cpp provider

### Added
- **Interactive dashboard MVP**
  - `tg.dashboard_app()` to build a Dash Cytoscape app
  - `tg.dashboard()` to launch interactive graph inspection locally
  - relation/category filters, node detail panel, and query result highlighting
- **Operational analyze report**
  - `tg.analyze()` summary with duplicates, conflicts, orphan tools, category coverage
  - CLI `analyze` now supports conflicts, orphans, categories, and JSON output
- **Remote fetch hardening** for spec and workflow ingest
  - shared safe network helper for remote OpenAPI / Swagger UI / Arazzo loading
  - private / localhost hosts blocked by default
  - response size limits, redirect limits, and content-type checks
  - explicit opt-in via `allow_private_hosts=True`
- **Execution policy layer** for tool calls
  - `ToolCallDecision` (`allow`, `confirm`, `deny`)
  - `ToolCallPolicy` and `ToolCallAssessment`
  - `tg.assess_tool_call()` API on top of `validate_tool_call()`
  - destructive auto-corrected calls denied by default
- **MCP server ingest**
  - `fetch_mcp_tools()` — HTTP JSON-RPC `tools/list`
  - `tg.ingest_mcp_server()` — fetch + ingest MCP tool list from server URL
  - supports both `{"result": {"tools": [...]}}` and `{"tools": [...]}`
- **Embedding persistence**
  - embedding vectors are now serialized with the graph
  - restorable embedding provider config is preserved when available
  - retrieval weights and diversity settings are restored on load

### Changed
- **Serialization format** now stores optional `retrieval_state`
  - embedding index state
  - retrieval weights
  - diversity configuration
- **Documentation sync**
  - WBS updated to match actual Phase 3 implementation status
  - `README.md`, `README-ko.md`, `README-ja.md`, `README-zh_CN.md` updated with
    MCP server ingest, execution policy, remote fetch safety, and embedding persistence

## [0.5.0] - 2026-03-07

### Added
- **CLI**: `python -m graph_tool_call` / `graph-tool-call` command
  - `ingest` — OpenAPI spec → graph.json
  - `analyze` — graph analysis + duplicate detection
  - `retrieve` — natural language tool search
  - `visualize` — export to HTML/GraphML/Cypher
  - `info` — graph summary (node/edge counts, categories)
- **Visualization**:
  - Pyvis HTML export — NodeType별 색상, degree 비례 노드 크기, RelationType별 엣지 스타일
  - Standalone HTML export (vis.js CDN, pyvis 불필요)
  - Progressive disclosure — 카테고리 더블클릭 시 하위 tool 토글 (1000+ 노드 대응)
  - GraphML export — Gephi, yEd 호환
  - Neo4j Cypher export — CREATE statement 생성
- **Conflict Detection**: `analyze/conflict.py`
  - 동일 리소스 PUT/DELETE 충돌 자동 감지
  - MCP annotation 기반 destructive vs non-destructive writer 충돌
  - `tg.detect_conflicts()` / `tg.apply_conflicts()` API
- **Commerce Preset**: `presets/commerce.py`
  - cart→order→payment→shipping→delivery→return→refund 워크플로우 자동 감지
  - `is_commerce_api()` — 3+ 커머스 스테이지 탐지
  - `tg.apply_commerce_preset()` — PRECEDES 관계 자동 추가
- **Model-Driven Search API**: `retrieval/model_driven.py`
  - `tg.search_api.search_tools(query)` — LLM function calling 노출용
  - `tg.search_api.get_workflow(tool_name)` — PRECEDES 체인 반환
  - `tg.search_api.browse_categories()` — 계층 트리 JSON
- **Examples**: `swagger_to_agent.py` — Petstore E2E (ingest→retrieve→export)
- **Tests**: 279개 (42개 신규)
- pyproject.toml `[tool.poetry.scripts]` entry point
- `visualization` extras group (pyvis)

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

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.10.1...HEAD
[0.10.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.8.0...v0.9.0
[0.5.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SonAIengine/graph-tool-call/releases/tag/v0.1.0
[0.8.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.5.0...v0.8.0
