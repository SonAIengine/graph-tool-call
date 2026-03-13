# graph-tool-call Documentation

## 문서 구조

```
docs/
├── README.md                   ← 현재 문서 (인덱스)
│
├── architecture/               # 아키텍처 & 데이터 모델
│   ├── overview.md             # 전체 아키텍처 (파이프라인, 레이어)
│   └── data-model.md           # ToolSchema, RelationType, NodeType
│
├── wbs/                        # WBS (Work Breakdown Structure)
│   ├── README.md               # Phase 전체 요약 + 진행 상황
│   ├── phase-0-mvp.md          # Phase 0: Core MVP (완료)
│   ├── phase-1-ingest.md       # Phase 1: Ingest + Dependency + Ordering
│   ├── phase-2-analyze.md      # Phase 2: Search Modes + Ontology Modes
│   ├── phase-3-production.md   # Phase 3: Visualization + Production
│   └── phase-4-community.md    # Phase 4: Dashboard + Community
│
├── design/                     # 설계 문서 (알고리즘 상세)
│   ├── spec-normalization.md   # OpenAPI 2.0/3.0/3.1 정규화 레이어
│   ├── ingest-openapi.md       # OpenAPI → ToolSchema 변환
│   ├── dependency-detection.md # 3-Layer Dependency Detection
│   ├── call-ordering.md        # API 호출 순서 감지 (PRECEDES)
│   ├── deduplication.md        # 5-Stage Dedup Pipeline
│   ├── retrieval-engine.md     # Hybrid Retrieval + wRRF
│   ├── annotation-retrieval.md # MCP Annotation-Aware Retrieval ← NEW
│   ├── search-modes.md         # 3-Tier 검색 아키텍처
│   ├── ontology-modes.md       # Auto/Manual/LLM 온톨로지 모드
│   ├── visualization-dashboard.md # 시각화 + 대시보드
│   └── openapi-guide.md        # OpenAPI 작성 가이드
│
└── research/                   # 리서치 노트
    ├── competitive-analysis.md # 경쟁 생태계 (RAG-MCP, LAPIS)
    ├── api-scale-data.md       # 실제 API 규모 데이터
    ├── framework-comparison.md # 프레임워크별 Swagger 차이
    ├── commerce-api-patterns.md # 커머스 API 패턴 ← NEW
    ├── graph-search-research.md # Graph Search + LLM Retrieval ← NEW
    ├── visualization-research.md # 시각화 라이브러리 비교 ← NEW
    └── references.md           # 논문/GitHub/커뮤니티 소스
```

## 읽는 순서

1. **전체 그림**: [architecture/overview.md](architecture/overview.md)
2. **진행 상황**: [wbs/README.md](wbs/README.md)
3. **현재 Phase 상세**: [wbs/phase-1-ingest.md](wbs/phase-1-ingest.md)
4. **설계 깊이 파기**: `design/` 디렉토리
5. **리서치 근거**: `research/` 디렉토리

## 최근 추가 (v2.5)

- **MCP Annotation-Aware Retrieval**: query intent ↔ tool annotation alignment
- **MCP tool ingest**: `inputSchema` + `annotations` 파싱, `tg.ingest_mcp_tools()`
- **Intent Classifier**: 한/영 키워드 기반 zero-LLM query intent 분류
- **Annotation Scorer**: intent↔annotation alignment scoring → wRRF 4번째 source
- **OpenAPI annotation 추론**: HTTP method → MCP annotation 자동 매핑 (RFC 7231)

## 최근 추가 (v0.9.0)

- **MCP server mode**: `graph-tool-call serve` — Claude Code, Cursor 등에서 .mcp.json으로 즉시 사용
- **`search` CLI**: `graph-tool-call search "query" --source <url>` — ingest+retrieve 원라인
- **SDK middleware**: `patch_openai()` / `patch_anthropic()` — 기존 코드 한 줄로 tool 자동 필터링
- **`[mcp]` extra**: MCP SDK optional dependency

## 최근 추가 (v0.8.0)

- **MCP server ingest**: `tg.ingest_mcp_server()`로 HTTP JSON-RPC `tools/list` 직접 수집
- **Remote fetch hardening**: private host 기본 차단, 응답 크기 제한, redirect 제한
- **Execution policy layer**: `tg.assess_tool_call()` → `allow / confirm / deny`
- **Embedding persistence**: `save()` / `load()` 시 embedding state + retrieval weights 복원
- **Operational analyze report**: `tg.analyze()`로 orphan/conflict/category coverage 요약
- **Interactive dashboard MVP**: `tg.dashboard()` / `tg.dashboard_app()`

### v2

- **API 호출 순서 감지**: PRECEDES 관계, 상태 머신, Arazzo spec
- **3-Tier 검색**: No-LLM → Small-LLM → Full-LLM
- **온톨로지 2모드**: Auto / LLM-Auto (Dashboard는 공통 시각화+편집 레이어)
- **OpenAPI 가이드**: 온톨로지 최적화를 위한 spec 작성법
