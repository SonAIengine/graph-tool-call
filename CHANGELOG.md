# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.28.0] - 2026-07-21

### Added
- **Persisted OpenAPI readiness fallback** — OpenAPI readiness analysis now
  reconstructs operation, consumes/produces, response, and context/auth
  coverage from stored `metadata.api_contract` rows when full
  `metadata.openapi` blocks are absent from XGEN-style collection graphs.
- **Query DTO execution contract** — OpenAPI JSON `content` query object
  parameters are exposed as searchable leaf inputs while preserving
  `schema_expanded_from`, `schema_expansion`, `content_type`, and `json_path`
  so HTTP execution can recompose the original wrapper JSON query parameter.

### Changed
- **Planflow missing-input metadata** — `Plan.metadata.user_input_slots` now
  includes OpenAPI contract metadata such as `required`, `location`,
  `json_path`, semantic tags, wrapper expansion metadata, and fallback reason
  fields for XGEN popup/resume flows.
- **OpenAPI query parameter expansion** — schema-backed and content-backed
  query object wrappers now share the same leaf-row extraction path, preserving
  required flags and schema hints consistently.

## [0.27.0] - 2026-07-20

### Added
- **XGEN candidate-set contract** — target candidates, producer candidates,
  expansion seeds, equivalence groups, rank signals, and action-priority
  helpers are exposed for API Collection adapters that need a small
  LLM-visible candidate set with audit evidence.
- **XGEN benchmark families** — deterministic commerce, admin, and workflow
  fixture suites now measure target recall, selector exactness, producer
  expansion lift, plan coverage, binding support, diagnostics coverage, and
  candidate counts.
- **XGEN scale gates** — live/snapshot OpenAPI scale runners now record
  snapshot provenance, tool/schema surface reduction, target selector metrics,
  plan-readiness metrics, and reusable gate blocks for X2BEE-scale validation.
- **BFCL milestone tooling** — 0.27/0.28 gate checks, hard-case bundle export,
  failure taxonomy, sweep attribution, and model-loop presentation controls
  make product and paper-readiness claims reproducible.
- **OpenAPI collection artifact builder** — graphify can produce a
  storage-ready collection artifact containing graph JSON, readiness report,
  source provenance, and build statistics for XGEN-style collection builds.

### Changed
- **Retrieval hardening** — guarded domain aliases, clause diversity, semantic
  phrase boosts, route-intent matching, and BFCL-specific candidate
  presentation controls improve top-5 recall without raising the default
  retrieval K.
- **Producer planning** — required producer selection now favors compact
  representative producer sets and excludes optional producers from executable
  plan candidates while preserving evidence in diagnostics.
- **Research docs** — `docs/research/xgen-tool-graph-goals.md`,
  `docs/research/validation-loop.md`, `docs/benchmarks.md`, and
  `docs/integrations/xgen-api-collection.md` document the 0.27 product
  candidate baseline and the remaining 0.28 paper-ready gap.

## [0.26.0] - 2026-07-20

### Added
- **OpenAPI collection readiness report** — `graph_tool_call.analyze.analyze_openapi_collection(...)` and `ToolGraph.analyze_openapi()` produce deterministic API Collection readiness summaries, issue codes, coverage metrics, graph-readiness metrics, and recommendations for XGEN-style registration flows.
- **OpenAPI inspect CLI** — `graph-tool-call inspect-openapi SOURCE [--json]` exposes the readiness report from the command line while preserving the existing private/internal URL safety policy.
- **OpenAPI execution contracts** — ingest now preserves richer request/response contracts including server variables, security contracts, parameter content, map/nullable/combinator/discriminator hints, response headers/links/envelope aliases, body media types, parameter serialization, root JSON bodies, nested array bodies, and raw request bodies.
- **OpenAPI execution diagnostics** — request preflight, argument validation, response diagnostics, response body views, raw array/body validation, discriminator validation, executable defaults, and body-view producer binding make plan readiness and execution failure causes more visible.
- **XGEN research validation loop** — fast development checks, XGEN API-scale acceptance/sweep benchmarks, contract signal ablations, and BFCL failure inspection artifacts document reproducible product-readiness gates.

### Changed
- **Field alias retrieval** — XGEN-style OpenAPI field aliases and execution contract signals are indexed for retrieval so opaque operation and field names remain searchable.
- **OpenAPI operation IDs** — duplicate operation IDs are deterministically deduplicated during ingest.

### Fixed
- **OpenAPI credential defaults** — implicit API key/credential fields no longer get unsafe default bindings.
- **Discriminator safety** — mismatched discriminator branch fields are rejected instead of being silently bound.

## [0.25.0] - 2026-07-18

### Added
- **Graphify public contract v2** — `build_io_contract()`, `expand_candidates_with_producers()`, `normalize_graph_edge()`, `merge_graph_edges()`, and `derive_plan_trace_edges()` move product-neutral XGEN Planflow graph logic into the engine.
- **Evidence-aware graphify retrieval** — `retrieve_graphify(..., include_evidence=True)` adds per-result `score_breakdown`, `expanded_from`, `edge_evidence`, and `stats.token_budget_used` without changing the legacy response keys.
- **Plan synthesis diagnostics** — `PlanSynthesisError.to_dict()` exposes structured `stage`, `reason`, `message`, and details. `Plan.metadata.synthesis` records selected producers, candidate signals, and user-input fallbacks.
- **Runner trace metadata** — `PlanRunner.run_stream(..., trace_metadata=...)` adds `stage`, `graph_tool_call_version`, `plan_id`, and caller trace metadata to dataclass events for SSE/log forwarding.
- **Planflow public contract docs** — `docs/planflow-public-contract.md` documents graphify, synthesis, and runner event contracts for XGEN-style adapters.

### Changed
- **Collection graph version** — `collection_graph_version` is now `2`; existing graphify v1 graphs remain readable because the new fields are additive.
- **BM25 indexing** — keyword retrieval now indexes `ai_metadata` summaries, use-when text, canonical action/resource, and IO field/semantic tags so enriched collections remain searchable even with opaque operation IDs.
- **Ambient inputs** — `PathSynthesizer` treats `kind=auth` like `kind=context`: supplied by entities/defaults or skipped, never producer-chained.

## [0.24.0] - 2026-07-18

### Added
- **Graphify collection metadata helper** — `graphify.annotate_graphify_metadata()` adds stable `graph_tool_call_version`, `collection_graph_version`, and `enrichment_status` fields for XGEN-style persisted API collection graphs without coupling the engine to product storage.
- **Enrichment status detection** — `graphify.detect_enrichment_status()` reports `empty` / `not_started` / `partial` / `complete` from serialized tool metadata.

### Fixed
- **Version drift** — synchronized `graph_tool_call.__version__` with the package version so CLI, serialized graph metadata, and product integrations report the same engine version.

## [0.23.0] - 2026-07-03

### Changed — Search-leaf 합성 정책 (조회는 단일 step)
- **`PathSynthesizer._resolve`** — target 의 `ai_metadata.canonical_action == "search"` 이면 required 데이터 필터를 producer 로 체인하지 않고 `${user_input.<field>}` 슬롯으로 surface. 조회(검색/목록)는 질의 leaf 이므로 모든 입력은 사용자가 주는 필터/조건이지, 무관한 producer 에서 끌어오는 값이 아니다. `getGoodsList` 류가 12개 필터마다 producer 를 붙여 단순 조회를 다단계 plan 으로 폭발시키던 문제의 근본 방지.
  - **`read` 는 제외** — read→detail 관용구(`getDetail(id)` ← search)는 정당한 체인이므로 dynamic-option 분기(5a)와 함께 보존.
  - **entity 매칭(1)·context(2)·optional-skip(3) 이후** 적용 — 사용자가 준 필터값은 그대로 바인딩되고, optional 필터는 이미 drop 되므로 이 게이트는 *required* 데이터 필터만 재작성.
  - `canonical_action` 이 없으면(un-enriched) no-op → 기존 동작 유지.
  - **동작 변경 주의**: enrich 된 search target 에 한해 합성 출력이 바뀐다(필터→user_input slot). 미enrich 컬렉션은 무영향.

### Fixed — recover 모드 종료 step 안전스킵 crash
- **`PlanRunner.run_stream`** — recover 모드에서 종료 step 이 safe-skip 되어 `context` 에 그 출력이 없을 때 `context[last_step_id]` 가 `KeyError` 로 죽던 것을 깔끔한 `PlanAborted`(`failed_step="<output_binding>"`)로 변환. `output_binding` 없는 단일 step(또는 전 step 스킵) plan 이 어떤 caller 에서도 crash 하지 않는다.

## [0.22.0] - 2026-07-03

### Added — Plan 실패 복구 루프 (A-P0-1)
- **`PlanRunner` 복구 모드** — `on_error="retry" | "recover"` (기존 `"abort"` 는 기본값, 바이트 단위 동일 동작 유지).
  - `retry_policy: RetryPolicy(max_attempts=2, backoff_base_ms=200, backoff_factor=2.0, retry_all=False)` — `kind="tool"` 실패만 지수 백오프로 재시도. step 이 `retryable=True` 로 opt-in 하거나 `retry_all=True` 일 때만. `StepTrace.retries` 실채움. `_sleep` 주입 가능(테스트용).
  - **recover 캐스케이드**: retry → skip(출력을 아무도 안 쓰면 안전 스킵) → replan(실패 producer 를 우회하도록 재합성). 모두 실패 시 기존처럼 abort.
  - 신규 additive 이벤트: `StepRetrying` / `StepSkipped` / `PlanRepaired`.
- **`plan.repair.PlanRepairer`** — 실패 step 을 우회해 재합성. `Plan.metadata` 의 target/entities 복원 + 완료 step 출력을 entity 로 병합 후 `synthesize(exclude_tools=...)`. target 자체 실패는 복구 불가(None). `RepairResult(plan, reused_outputs, excluded_tools)`.
- **`plan.deps`** — `compute_step_deps(plan)`(step→선행 step 의존), `is_output_consumed(plan, step_id, after_index)`(안전 스킵 판정). binding 정규식 재사용.
- **`plan.extraction`** — `find_value_paths(output, *, field_name, ...)`(응답 트리 BFS: exact→loose key, 랭크된 `PathCandidate`), `extract_produced_entities(tool_meta, output)`(produces 스키마→entity, semantic+field 양쪽 키). `ValueExtractorLLM` Protocol(P1 훅).
- **`PlanStep.depends_on`** — args 바인딩이 참조하는 선행 step id (synthesizer 가 채움). **빈 리스트=선형 시맨틱 유지**, 실행기는 여전히 순차 실행(DAG defer). 복구/UI 용 힌트.
- **`PathSynthesizer.synthesize(exclude_tools=...)`** — keyword-only, 기존 `_find_producer(excluded=...)` 재사용. 기본 `None` 으로 하위호환.
- **`benchmarks/run_recovery_benchmark.py`** — fault-injection 으로 recovery_rate 측정(baseline abort 25% → recover 100%).

### Added — 파라미터 할당 강화 (A-P0-2)
- **`plan.coercion.coerce_args(tool, args, *, fuzzy_enum=True, cast_types=True)`** — 실행 직전 resolved args 를 도구 스키마에 맞춰 정리(non-mutating). 타입 캐스트(`"3"`→`3`, `"true"`→`True`), fuzzy enum(casefold+구분자 폴딩, `ToolParameter.enum` 소비). `CoercionReport(corrected, changes, unresolved)`. bool→int 재캐스트 금지 등 보수적.
- **`PlanRunner` 파라미터 훅** (전부 opt-in, 기본 off):
  - `tools: dict[str, ToolSchema]` — coercion 이 참조할 도구 스키마. 없으면 no-op.
  - `validate_args="coerce"` — 실행 전 `coerce_args` 적용, `ArgsCoerced` 이벤트. 기본 `"off"`.
  - `binding_recovery=True` — `${sN.path}` 가 실제 응답 모양과 안 맞으면 `find_value_paths` 로 트리 검색해 단일 명확후보 자동수리, `BindingRepaired` 이벤트. 애매(동률 후보)하면 회수 포기→기존처럼 abort(silent 오선택 방지).
- **`plan.extraction.ValueExtractorLLM`** Protocol — 값 추출 LLM 훅 시그니처(P1 seam, 미사용).

### Added — 수천 규모 검색 고도화 (A-P1-5)
- **`retrieval.prefilter.CategoryPrefilter`** — 대형 코퍼스에서 카테고리 토큰 매치(+임베딩 있으면 카테고리 센트로이드) 로 후보 풀을 만들고 **BM25 top-N 을 반드시 union(recall-preserving 가드)**. 신호 약하면 `None`(전체 코퍼스). 풀 크기 `[min_pool=150, max_pool=500]` 로 bound(좁으면 1-hop 그래프 이웃으로 확장, 넓으면 cap — cap 시 BM25-top 은 절대 제외 안 함).
- **`RetrievalEngine` 스케일 훅** — `enable_prefilter()`(기본 off, `n>=500` 에서만 발동), `resource_first_search` 를 프리필터와 그래프 채널이 **1회만 공유**. embedding/annotation/graph 채널에 pool `restrict` 전파(keyword 는 full 유지 = recall 백본). `n>1000` adaptive weight 티어 추가(임베딩 강화 0.55). `n>300` & 임베딩 미설정 시 최초 retrieve 때 1회 `warnings.warn`.
- **BM25 name-token 캐싱** — `_name_subsequence_boost` 가 매 쿼리 전체 도구명을 재토큰화·재스테밍하던 것을 인덱스 빌드 시 캐싱. **5000 도구 latency p50 80ms→28ms (약 2.9x), recall 무영향.** `BM25Scorer.score(query, *, restrict=None)` 추가(pool 한정 스코어링; `None`=기존 동일).
- **dynamic-k + 페이지네이션** — `search_tools(query, top_k, page)` 응답에 `page`/`has_more`/`hint`. `elbow_cut_k()`(top 2k 스코어 elbow 컷: 확신 높으면 2~3, 모호하면 k). `ToolGraph.as_tools(adaptive_k=None)` 기본 off(하위호환). `tool_graph.py` + `mcp_server.py` 양쪽.
- **`ToolGraph.tune_for_scale()`** — 프리필터 on + diversity λ=0.7 + dynamic-k on 원클릭 프리셋. **`enable_embedding("auto")`** — sentence-transformers→OpenAI env→Ollama 순 자동 감지.
- **`benchmarks/run_scale_benchmark.py`** — 번들 스펙(github/k8s/ecommerce) 네임스페이스 변형으로 3k/5k 합성 코퍼스. recall@5 / latency p50·p95 / 응답 크기 측정, 프리필터 off/on 비교. **recall delta = 0(프리필터 recall 보존)**.

## [0.21.0] - 2026-06-29

### Added
- **Pluggable BM25 tokenizer** — 커스텀 토크나이저 주입 훅
  - `BM25Scorer(..., *, tokenizer=...)` keyword-only 인자. 기본 `None` 은 기존 `_tokenize` 와 바이트 단위 동일 (100% 후방호환).
  - `ToolGraph.set_tokenizer("kiwi" | callable | None)` — keyword 검색 전체(그리고 동일 BM25 인스턴스를 공유하는 graphify seed)에 토크나이저 전파. 엔진 invalidate 후 재생성 시 자동 재주입.
  - `wrap_tokenizer()` 자동판별 (`wrap_embedding`/`wrap_llm` 패턴) + `KiwiTokenizer` 하이브리드: 영문 파이프라인은 그대로 두고 한글 span 만 Kiwi 형태소로 분리, Kiwi 가 못 쪼갠 OOV 는 char-bigram 으로 폴백.
  - `kiwipiepy` optional dependency + `korean` extra (`pip install graph-tool-call[korean]`). 미설치 시 라이브러리 import 에 영향 없음 (lazy import).
  - 효과: 한국어 무공백 복합어("배송상태조회")가 char-bigram 노이즈("송상","태조") 없이 깨끗한 형태소로 분리 → `_KO_EN_DICT` 사전 적중률 상승 → 한↔영 cross-language 검색 정확도 향상.

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

[Unreleased]: https://github.com/SonAIengine/graph-tool-call/compare/v0.28.0...HEAD
[0.25.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.20.1...v0.21.0
[0.20.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.13.1...v0.18.0
[0.13.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/SonAIengine/graph-tool-call/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.8.0...v0.9.0
[0.5.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SonAIengine/graph-tool-call/releases/tag/v0.1.0
[0.8.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.5.0...v0.8.0
[0.28.0]: https://github.com/SonAIengine/graph-tool-call/compare/v0.27.0...v0.28.0
