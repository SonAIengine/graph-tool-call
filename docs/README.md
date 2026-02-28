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
│   ├── call-ordering.md        # API 호출 순서 감지 (PRECEDES) ← NEW
│   ├── deduplication.md        # 5-Stage Dedup Pipeline
│   ├── retrieval-engine.md     # Hybrid Retrieval + RRF
│   ├── search-modes.md         # 3-Tier 검색 아키텍처 ← NEW
│   ├── ontology-modes.md       # Auto/Manual/LLM 온톨로지 모드 ← NEW
│   ├── visualization-dashboard.md # 시각화 + 대시보드 ← NEW
│   └── openapi-guide.md        # OpenAPI 작성 가이드 ← NEW
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

## 최근 추가 (v2)

- **API 호출 순서 감지**: PRECEDES 관계, 상태 머신, Arazzo spec
- **3-Tier 검색**: No-LLM → Small-LLM → Full-LLM
- **온톨로지 3모드**: Auto / Manual(Dashboard) / LLM-Enhanced
- **시각화**: Pyvis HTML → Dash Cytoscape Dashboard
- **OpenAPI 가이드**: 온톨로지 최적화를 위한 spec 작성법
- **커머스 패턴**: 주문/결제/배송 워크플로우 자동 감지
