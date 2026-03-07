# WBS (Work Breakdown Structure)

## Phase 전체 요약

| Phase | 이름 | 핵심 산출물 | 상태 | 기간 |
|-------|------|------------|------|------|
| **0** | Core MVP | graph + retrieval 기본 동작 | ✅ 완료 | - |
| **1** | Ingest + Dependency | OpenAPI ingest, dependency/ordering detection, retrieval 개선 | ✅ 완료 | - |
| **2** | Analyze + Search | dedup, embedding, ontology modes, search tiers, from_url() | ✅ 완료 | - |
| **2.5** | MCP Annotation | MCP ingest, intent classifier, annotation-aware retrieval | ✅ 완료 | - |
| **3** | Production | CLI, 시각화, conflict detection, commerce preset | ✅ 완료 | - |
| **4** | Community | LangChain 등록, interactive dashboard, 블로그, 최적화 | ⬜ 대기 | 2주 |

## WBS 전체 트리

```
graph-tool-call
│
├── Phase 0: Core MVP ✅
│   ├── 0-1. ToolSchema + 포맷 파서 ✅
│   ├── 0-2. GraphEngine (NetworkX) ✅
│   ├── 0-3. Ontology (schema + builder) ✅
│   ├── 0-4. Retrieval (keyword + graph) ✅
│   ├── 0-5. LangChain integration ✅
│   ├── 0-6. ToolGraph facade + serialization ✅
│   └── 0-7. Tests (32 passing) ✅
│
├── Phase 1: Ingest + Dependency + Ordering ✅
│   ├── 1-1. 버그 수정 (tags TypeError, keyword scoring) ✅
│   ├── 1-2. Spec Normalization Layer ✅
│   │   ├── 1-2a. 버전 감지 (swagger 2.0 / openapi 3.0 / 3.1) ✅
│   │   ├── 1-2b. Swagger 2.0 → 3.0 구조 변환 ✅
│   │   ├── 1-2c. nullable 정규화 (3가지 패턴 통일) ✅
│   │   └── 1-2d. $ref 경로 정규화 ✅
│   ├── 1-3. OpenAPI Ingest ✅
│   │   ├── 1-3a. spec 로딩 (URL/파일, JSON/YAML) ✅
│   │   ├── 1-3b. $ref resolution ✅
│   │   ├── 1-3c. operation → ToolSchema 변환 ✅
│   │   ├── 1-3d. 대형 request body 처리 ✅
│   │   └── 1-3e. deprecated 필터링 ✅
│   ├── 1-4. Dependency & Ordering Detection ✅
│   │   ├── 1-4a. Layer 1: path hierarchy + CRUD pattern ✅
│   │   ├── 1-4b. Layer 1: $ref 스키마 공유 감지 ✅
│   │   ├── 1-4c. Layer 2: response→parameter name matching ✅
│   │   ├── 1-4d. naming convention 정규화 ✅
│   │   ├── 1-4e. confidence score ✅
│   │   ├── 1-4f. false positive 필터링 ✅
│   │   ├── 1-4g. PRECEDES RelationType 추가 ✅
│   │   ├── 1-4h. CRUD workflow ordering ✅
│   │   └── 1-4i. State machine detection (enum status) ⬜ Phase 2로 이월
│   ├── 1-5. Auto-categorization ✅
│   │   ├── 1-5a. tag 기반 카테고리 생성 ✅
│   │   └── 1-5b. path prefix fallback (tag 없는 spec) ✅
│   ├── 1-6. Python callable ingest ✅
│   │   ├── 1-6a. inspect.signature → ToolSchema ✅
│   │   └── 1-6b. docstring → description ✅
│   ├── 1-7. Retrieval 개선 ✅
│   │   ├── 1-7a. BM25-style keyword scoring ✅
│   │   ├── 1-7b. RRF score fusion ✅
│   │   ├── 1-7c. tags 기반 scoring 통합 ✅
│   │   ├── 1-7d. SearchMode enum (BASIC/ENHANCED/FULL) ✅
│   │   └── 1-7e. Model-Driven API 스켈레톤 ⬜ Phase 3으로 이월
│   ├── 1-8. OpenAPI 작성 가이드 문서 ✅
│   └── 1-9. Tests + Examples ✅
│       ├── 1-9a. Petstore E2E 테스트 ✅
│       ├── 1-9b. Swagger 2.0/3.0/3.1 각각 테스트 ✅
│       ├── 1-9c. Dependency + ordering detection 테스트 ✅
│       └── 1-9d. examples/swagger_to_agent.py ⬜ Phase 2로 이월
│
├── Phase 2: Analyze + Search Modes + Ontology Modes ✅
│   ├── 2-1. Deduplication pipeline
│   │   ├── 2-1a. Stage 1-3: hash + name fuzzy + schema Jaccard
│   │   ├── 2-1b. Stage 4-5: semantic + composite score
│   │   ├── 2-1c. find_duplicates() API
│   │   └── 2-1d. merge_duplicates() + MergeStrategy
│   ├── 2-2. Embedding 검색
│   │   ├── 2-2a. all-MiniLM-L6-v2 / multilingual-e5 연동
│   │   ├── 2-2b. EmbeddingIndex 실제 검색 통합
│   │   └── 2-2c. RetrievalEngine에 embedding score 연결
│   ├── 2-3. Ontology Modes (Auto / LLM-Auto) ← EXPANDED
│   │   ├── 2-3a. Auto mode 완성 (embedding clustering)
│   │   ├── 2-3b. OntologyLLM 추상화 (Provider 인터페이스) ← NEW
│   │   ├── 2-3c. Ollama provider ← NEW
│   │   ├── 2-3d. vLLM provider ← NEW
│   │   ├── 2-3e. OpenAI compatible provider ← NEW
│   │   ├── 2-3f. Batch 관계 추론 (50개 단위) ← NEW
│   │   └── 2-3g. LLM 카테고리 제안 ← NEW
│   ├── 2-4. Search Modes ← NEW SECTION
│   │   ├── 2-4a. SearchLLM 추상화 (Ollama/vLLM/OpenAI)
│   │   ├── 2-4b. Tier 1: Query expansion
│   │   ├── 2-4c. Tier 2: Intent decomposition
│   │   └── 2-4d. wRRF (weighted RRF) 적응 가중치
│   ├── 2-5. Arazzo Specification 지원 ← NEW
│   │   ├── 2-5a. Arazzo spec 파서
│   │   └── 2-5b. 워크플로우 → PRECEDES 변환
│   └── 2-6. 벤치마크
│       ├── 2-6a. Tool set 구성 (Petstore/GitHub/Synthetic)
│       ├── 2-6b. Precision/Recall/NDCG/Workflow Coverage 측정
│       ├── 2-6c. Tier별 Recall/Precision 비교 ← NEW
│       └── 2-6d. baseline 비교 (all-tools, random, embedding-only)
│
├── Phase 2.5: MCP Annotation-Aware Retrieval ✅
│   ├── 2.5-1. MCPAnnotations 모델 + ToolSchema 확장 ✅
│   ├── 2.5-2. OpenAPI ingest HTTP→annotation 자동 추론 (RFC 7231) ✅
│   ├── 2.5-3. MCP tool list ingest (ingest/mcp.py) ✅
│   ├── 2.5-4. Intent Classifier (한/영 키워드, zero-LLM) ✅
│   ├── 2.5-5. Annotation Scorer (intent↔annotation alignment) ✅
│   ├── 2.5-6. RetrievalEngine 4-source wRRF 통합 ✅
│   ├── 2.5-7. 부가 통합 (builder, similarity, exports) ✅
│   └── 2.5-8. 테스트 74개 추가 (255개 total) ✅
│
├── Phase 3: Production + Visualization ✅
│   ├── 3-1. (완료 — Phase 2.5로 이동) MCP server ingest ✅
│   ├── 3-2. Conflict detection 강화 ✅
│   ├── 3-3. CLI (ingest/analyze/retrieve/visualize/info) ✅
│   ├── 3-4. Visualization — Static HTML ✅
│   │   ├── 3-4a. Pyvis HTML export ✅
│   │   ├── 3-4b. Progressive disclosure (standalone vis.js) ✅
│   │   ├── 3-4c. Neo4j Cypher export ✅
│   │   └── 3-4d. GraphML export ✅
│   ├── 3-5. Model-Driven Search 완성 ✅
│   │   ├── 3-5a. search_tools LLM tool 노출 ✅
│   │   ├── 3-5b. get_workflow 워크플로우 조회 ✅
│   │   └── 3-5c. browse_categories 트리 조회 ✅
│   ├── 3-6. llama.cpp provider ⬜ Phase 4로 이월
│   ├── 3-7. 커머스 도메인 프리셋 ✅
│   ├── 3-8. GitHub Actions CI ✅
│   └── 3-9. PyPI 배포 ⬜ Phase 4로 이월
│
└── Phase 4: Community + Dashboard ⬜
    ├── 4-1. Interactive Dashboard (Dash Cytoscape) ← NEW
    │   ├── 4-1a. 그래프 탐색 UI
    │   ├── 4-1b. 수동 편집 (관계 추가/삭제)
    │   ├── 4-1c. 검색 테스트 UI
    │   └── 4-1d. 관계 검증 (confirm/reject)
    ├── 4-2. LangChain community package 등록
    ├── 4-3. 블로그: "Why Graph > Vector for Tool Retrieval"
    ├── 4-4. (선택) LAPIS 포맷 출력
    └── 4-5. (선택) Rust(PyO3+petgraph) 최적화
```

## 피드백 반영 요약 (v2)

| # | 피드백 | 반영 위치 | 상태 |
|---|--------|----------|------|
| 1 | 입력 소스 = 표준 포맷 확인 | 이미 반영 (OpenAPI/MCP/LangChain) | ✅ |
| 2 | OpenAPI 작성 가이드 | 1-8, [design/openapi-guide.md](../design/openapi-guide.md) | ⬜ |
| 3 | API 호출 순서/우선순위 | 1-4g~i, 2-5, [design/call-ordering.md](../design/call-ordering.md) | ⬜ |
| 4 | 온톨로지 2모드 (Auto/LLM-Auto) + Dashboard 공통 | 2-3, 3-6, 4-1, [design/ontology-modes.md](../design/ontology-modes.md) | ⬜ |
| 5 | Search modes 개선 | 1-7d~e, 2-4, 3-5, [design/search-modes.md](../design/search-modes.md) | ⬜ |

## 성공 기준

### 정량적
- Petstore (5 endpoints) → dependency + ordering 감지 ✅ (CRUD 패턴 전체 감지)
- 500-tool set에서 Workflow Coverage 20%+ 개선 (vs 벡터만)
- Retrieval latency: 100ms 이내 (500 tools, CPU, Tier 0)
- Deduplication: 0.85 threshold에서 precision 90%+
- Tier 1 (Small LLM): Recall +15% 개선 (vs Tier 0)

### 정성적
- `tg.ingest_openapi(url)` 한 줄로 Swagger → 관계+순서 포함 tool graph
- LLM 없이도 검색 동작, LLM 있으면 품질 향상
- 1.5B 모델로도 검색 개선 가능
- LangChain 없이 standalone 동작

## 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| OpenAPI edge case (anyOf, $ref 순환) | Ingest 실패 | 보수적 파싱 + graceful fallback |
| Dependency/ordering false positive | 신뢰도 저하 | confidence score + threshold |
| Embedding 의존성 무거움 | 설치 장벽 | strict optional |
| 대형 spec (1000+) 성능 | 느린 분석 | incremental + batch |
| auto_organize LLM 비용 | 사용 장벽 | clustering fallback (LLM 불필요) |
| 다국어 검색 품질 | 한국어 쿼리 낮은 Recall | multilingual embedding 모델 |
| Dashboard 복잡도 | 개발 지연 | Phase 3 static → Phase 4 interactive |

## 상세 문서 링크

- [Phase 0: Core MVP](phase-0-mvp.md)
- [Phase 1: Ingest + Dependency + Ordering](phase-1-ingest.md)
- [Phase 2: Analyze + Search + Ontology Modes](phase-2-analyze.md)
- [Phase 3: Production + Visualization](phase-3-production.md)
- [Phase 4: Community + Dashboard](phase-4-community.md)
