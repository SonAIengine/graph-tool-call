# graph-tool-call Documentation

## 문서 구조

```
docs/
├── README.md                 ← 현재 문서 (인덱스)
│
├── architecture/             # 아키텍처 & 데이터 모델
│   ├── overview.md           # 전체 아키텍처 (파이프라인, 레이어)
│   └── data-model.md         # ToolSchema, RelationType, NodeType
│
├── wbs/                      # WBS (Work Breakdown Structure)
│   ├── README.md             # Phase 전체 요약 + 진행 상황
│   ├── phase-0-mvp.md        # Phase 0: Core MVP (완료)
│   ├── phase-1-ingest.md     # Phase 1: Ingest + Dependency + Retrieval
│   ├── phase-2-analyze.md    # Phase 2: Dedup + Embedding + Auto-organize
│   ├── phase-3-production.md # Phase 3: MCP + CLI + 배포
│   └── phase-4-community.md  # Phase 4: 커뮤니티 + 최적화
│
├── design/                   # 설계 문서 (알고리즘 상세)
│   ├── spec-normalization.md # OpenAPI 2.0/3.0/3.1 정규화 레이어
│   ├── ingest-openapi.md     # OpenAPI → ToolSchema 변환
│   ├── dependency-detection.md # 3-Layer Dependency Detection
│   ├── deduplication.md      # 5-Stage Dedup Pipeline
│   └── retrieval-engine.md   # Hybrid Retrieval + RRF
│
├── research/                 # 리서치 노트
│   ├── competitive-analysis.md # 경쟁 생태계 (bigtool, RAG-MCP, LAPIS)
│   ├── api-scale-data.md     # 실제 API 규모 데이터
│   ├── framework-comparison.md # 프레임워크별 Swagger 차이
│   └── references.md         # 논문/GitHub/커뮤니티 소스
│
└── PLAN.md                   # (레거시) 통합 플랜 원본
```

## 읽는 순서

1. **전체 그림**: [architecture/overview.md](architecture/overview.md)
2. **진행 상황**: [wbs/README.md](wbs/README.md)
3. **현재 Phase 상세**: [wbs/phase-1-ingest.md](wbs/phase-1-ingest.md)
4. **설계 깊이 파기**: `design/` 디렉토리
5. **리서치 근거**: `research/` 디렉토리
