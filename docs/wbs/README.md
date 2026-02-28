# WBS (Work Breakdown Structure)

## Phase 전체 요약

| Phase | 이름 | 핵심 산출물 | 상태 | 기간 |
|-------|------|------------|------|------|
| **0** | Core MVP | graph + retrieval 기본 동작 | ✅ 완료 | - |
| **1** | Ingest + Dependency | OpenAPI ingest, dependency detection, retrieval 개선 | ⬜ 진행 예정 | 2주 |
| **2** | Analyze + Embedding | dedup, embedding 검색, auto-organize, bigtool 연동 | ⬜ 대기 | 2주 |
| **3** | Production | MCP ingest, CLI, 시각화, PyPI 배포 | ⬜ 대기 | 2주 |
| **4** | Community | LangChain 등록, 블로그, 최적화 | ⬜ 대기 | 2주 |

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
├── Phase 1: Ingest + Dependency ⬜
│   ├── 1-1. 버그 수정 (tags TypeError, keyword scoring)
│   ├── 1-2. Spec Normalization Layer ← NEW
│   │   ├── 1-2a. 버전 감지 (swagger 2.0 / openapi 3.0 / 3.1)
│   │   ├── 1-2b. Swagger 2.0 → 3.0 구조 변환
│   │   ├── 1-2c. nullable 정규화 (3가지 패턴 통일)
│   │   └── 1-2d. $ref 경로 정규화
│   ├── 1-3. OpenAPI Ingest
│   │   ├── 1-3a. spec 로딩 (URL/파일, JSON/YAML)
│   │   ├── 1-3b. $ref resolution
│   │   ├── 1-3c. operation → ToolSchema 변환
│   │   ├── 1-3d. 대형 request body 처리
│   │   └── 1-3e. deprecated 필터링
│   ├── 1-4. Dependency Detection
│   │   ├── 1-4a. Layer 1: path hierarchy + CRUD pattern
│   │   ├── 1-4b. Layer 1: $ref 스키마 공유 감지
│   │   ├── 1-4c. Layer 2: response→parameter name matching
│   │   ├── 1-4d. naming convention 정규화
│   │   ├── 1-4e. confidence score + cycle detection
│   │   └── 1-4f. false positive 필터링
│   ├── 1-5. Auto-categorization
│   │   ├── 1-5a. tag 기반 카테고리 생성
│   │   └── 1-5b. path prefix fallback (tag 없는 spec)
│   ├── 1-6. Python callable ingest
│   │   ├── 1-6a. inspect.signature → ToolSchema
│   │   └── 1-6b. docstring → description
│   ├── 1-7. Retrieval 개선
│   │   ├── 1-7a. BM25-style keyword scoring
│   │   ├── 1-7b. RRF score fusion
│   │   └── 1-7c. tags 기반 scoring 통합
│   └── 1-8. Tests + Examples
│       ├── 1-8a. Petstore E2E 테스트
│       ├── 1-8b. Swagger 2.0/3.0/3.1 각각 테스트
│       └── 1-8c. examples/swagger_to_agent.py
│
├── Phase 2: Analyze + Embedding ⬜
│   ├── 2-1. Deduplication pipeline
│   │   ├── 2-1a. Stage 1-3: hash + name fuzzy + schema Jaccard
│   │   ├── 2-1b. Stage 4-5: semantic + composite score
│   │   ├── 2-1c. find_duplicates() API
│   │   └── 2-1d. merge_duplicates() + MergeStrategy
│   ├── 2-2. Embedding 검색
│   │   ├── 2-2a. all-MiniLM-L6-v2 연동
│   │   ├── 2-2b. EmbeddingIndex 실제 검색 통합
│   │   └── 2-2c. RetrievalEngine에 embedding score 연결
│   ├── 2-3. Auto-organize
│   │   ├── 2-3a. LLM 기반 자동 온톨로지
│   │   └── 2-3b. embedding clustering fallback
│   ├── 2-4. bigtool 연동
│   │   ├── 2-4a. retrieve_tools_function adapter
│   │   └── 2-4b. examples/bigtool_plugin.py
│   └── 2-5. 벤치마크
│       ├── 2-5a. Tool set 구성 (Petstore/GitHub/Synthetic)
│       ├── 2-5b. Precision/Recall/NDCG/Workflow Coverage 측정
│       └── 2-5c. baseline 비교 (all-tools, random, embedding-only)
│
├── Phase 3: Production ⬜
│   ├── 3-1. MCP server ingest
│   ├── 3-2. Conflict detection 강화
│   ├── 3-3. CLI (ingest/analyze/retrieve)
│   ├── 3-4. 그래프 시각화 (HTML export)
│   ├── 3-5. GitHub Actions CI
│   └── 3-6. PyPI 배포
│
└── Phase 4: Community ⬜
    ├── 4-1. LangChain community package 등록
    ├── 4-2. bigtool 연동 PR
    ├── 4-3. 블로그 작성
    ├── 4-4. (선택) LAPIS 포맷 출력
    └── 4-5. (선택) Rust 최적화
```

## 성공 기준

### 정량적
- Petstore (20 endpoints) → dependency 감지 precision 80%+
- 500-tool set에서 Workflow Coverage 20%+ 개선 (vs 벡터만)
- Retrieval latency: 100ms 이내 (500 tools, CPU)
- Deduplication: 0.85 threshold에서 precision 90%+

### 정성적
- `tg.ingest_openapi(url)` 한 줄로 Swagger → 관계 포함 tool graph
- bigtool 연동 3줄
- LangChain 없이 standalone 동작

## 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| OpenAPI edge case (anyOf, $ref 순환) | Ingest 실패 | 보수적 파싱 + graceful fallback |
| Dependency false positive | 신뢰도 저하 | confidence score + threshold |
| Embedding 의존성 무거움 | 설치 장벽 | strict optional |
| 대형 spec (1000+) 성능 | 느린 분석 | incremental + batch |
| auto_organize LLM 비용 | 사용 장벽 | clustering fallback |

## 상세 문서 링크

- [Phase 0: Core MVP](phase-0-mvp.md)
- [Phase 1: Ingest + Dependency](phase-1-ingest.md)
- [Phase 2: Analyze + Embedding](phase-2-analyze.md)
- [Phase 3: Production](phase-3-production.md)
- [Phase 4: Community](phase-4-community.md)
