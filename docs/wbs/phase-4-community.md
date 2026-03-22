# Phase 4: Community + Interactive Dashboard

**상태**: 🟨 일부 진행
**목표 기간**: 2주
**선행 조건**: Phase 3 완료

## WBS 상세

### 4-1. Interactive Dashboard (Dash Cytoscape) ← NEW

설계 문서: [design/visualization-dashboard.md](../design/visualization-dashboard.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4-1a | 그래프 탐색 UI (줌/팬/클릭 상세) | `dashboard/app.py` | ✅ |
| 4-1b | 수동 편집 (관계 추가/삭제) | Workflow Editor HTML로 대체 | ✅ |
| 4-1c | 검색 테스트 UI (쿼리 → 결과 하이라이트) | `dashboard/app.py` | ✅ |
| 4-1d | 관계 검증 (confirm/reject) | `dashboard/app.py` | ⬜ |

**세부**:
- Dash Cytoscape 기반 interactive dashboard
- 좌측: 필터 패널 (relation type, category, confidence)
- 중앙: 그래프 뷰 (Cytoscape.js dagre/cose 레이아웃)
- 하단: 검색 바 + 결과 + 노드 상세
- `tg.dashboard(port=8050)` 으로 시작
- 현재 구현 범위: 탐색 UI, 카테고리/관계 필터, query 기반 결과 하이라이트, 노드 상세 패널

---

### 4-2. LangChain Community Package 등록

| ID | 작업 | 상태 |
|----|------|------|
| 4-2a | langchain-community PR 제출 | ⬜ |

---

### 4-3. 블로그

| ID | 작업 | 상태 |
|----|------|------|
| 4-3a | "Why Graph > Vector for Tool Retrieval" 블로그 작성 | ⬜ |

---

### 4-4. (선택) LAPIS 포맷 출력 지원

| ID | 작업 | 상태 |
|----|------|------|
| 4-4a | retrieve 결과를 LAPIS 포맷으로 변환 | ⬜ |

---

### 4-5. (선택) Rust 최적화

| ID | 작업 | 상태 |
|----|------|------|
| 4-5a | PyO3 + petgraph로 그래프 연산 최적화 | ⬜ |

---

## Phase 4.5: Workflow + Scale (추가됨)

**상태**: ✅ 완료

### 4.5-1. plan_workflow() API ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-1a | WorkflowPlanner (resource-first → chain → topo sort) | `workflow.py` | ✅ |
| 4.5-1b | 수동 편집 (insert/remove/reorder/set_param_mapping) | `workflow.py` | ✅ |
| 4.5-1c | JSON save/load | `workflow.py` | ✅ |
| 4.5-1d | LLM-assisted 체인 보강 | `workflow.py` | ✅ |

### 4.5-2. Workflow 시각화 편집 툴 ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-2a | 브라우저 기반 드래그앤드롭 에디터 | `static/workflow_editor.html` | ✅ |
| 4.5-2b | plan.open_editor() Python API 연동 | `workflow.py` | ✅ |

### 4.5-3. SSE/Streamable-HTTP transport ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-3a | serve --transport sse/streamable-http | `mcp_server.py` | ✅ |
| 4.5-3b | proxy --transport sse/streamable-http | `mcp_proxy.py` | ✅ |

### 4.5-4. Graph 아키텍처 전환 ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-4a | Graph → candidate injection (wRRF에서 분리) | `retrieval/engine.py` | ✅ |
| 4.5-4b | set_weights() 버그 수정 (adaptive 덮어쓰기) | `retrieval/engine.py` | ✅ |
| 4.5-4c | Resource-first search 범용화 (GitHub alias 제거) | `retrieval/graph_search.py` | ✅ |

### 4.5-5. 경쟁 벤치마크 ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-5a | 6개 retrieval 전략 공정 비교 | `benchmarks/run_competitive.py` | ✅ |
| 4.5-5b | 1068 tool 스트레스 테스트 (GitHub full API) | `benchmarks/` | ✅ |

### 4.5-6. Retrieval 개선 ✅

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4.5-6a | Intent 사전 확장 (+16 동사) | `retrieval/intent.py` | ✅ |
| 4.5-6b | 한영 사전 35→114개 확장 | `ko_en_dict.py` | ✅ |
| 4.5-6c | Confidence-aware wRRF | `retrieval/engine.py` | ✅ |
