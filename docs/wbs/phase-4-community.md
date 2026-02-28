# Phase 4: Community + Interactive Dashboard

**상태**: ⬜ 대기
**목표 기간**: 2주
**선행 조건**: Phase 3 완료

## WBS 상세

### 4-1. Interactive Dashboard (Dash Cytoscape) ← NEW

설계 문서: [design/visualization-dashboard.md](../design/visualization-dashboard.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 4-1a | 그래프 탐색 UI (줌/팬/클릭 상세) | `dashboard/app.py` | ⬜ |
| 4-1b | 수동 편집 (관계 추가/삭제) | `dashboard/app.py` | ⬜ |
| 4-1c | 검색 테스트 UI (쿼리 → 결과 하이라이트) | `dashboard/app.py` | ⬜ |
| 4-1d | 관계 검증 (confirm/reject) | `dashboard/app.py` | ⬜ |

**세부**:
- Dash Cytoscape 기반 interactive dashboard
- 좌측: 필터 패널 (relation type, category, confidence)
- 중앙: 그래프 뷰 (Cytoscape.js dagre/cose 레이아웃)
- 하단: 검색 바 + 결과 + 노드 상세
- `tg.dashboard(port=8050)` 으로 시작

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
