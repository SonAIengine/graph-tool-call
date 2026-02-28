# Visualization Dashboard — 설계 문서

**WBS**: 3-4 (Phase 3 확장)
**파일**: `visualization/`, `dashboard/`
**리서치**: Pyvis, Cytoscape.js, Dash Cytoscape, Streamlit

## 동기

Tool graph를 시각적으로 탐색하고 수동으로 편집할 수 있는 대시보드가 필요:
- 1000+ tool의 관계를 Neo4j처럼 시각화
- 수동 온톨로지 편집 (노드/엣지 추가·삭제)
- 자동 감지된 관계 검증 (confirm/reject)

## 라이브러리 비교

| | Pyvis | Cytoscape.js | Dash Cytoscape | Streamlit |
|--|-------|-------------|---------------|-----------|
| **복잡도** | 낮음 | 중간 | 중간 | 낮음 |
| **인터랙션** | 기본 드래그 | 풀 인터랙션 | 풀 + Dash callback | 기본 |
| **노드 규모** | ~500 | ~5000 | ~5000 | ~200 |
| **편집 기능** | 없음 | 커스텀 가능 | callback 가능 | 제한적 |
| **배포** | HTML 파일 | 웹앱 | 웹앱 | 웹앱 |
| **Python 통합** | ★★★ | ★ | ★★★ | ★★★ |

### 선택: 2단계 접근

1. **Phase 3 (MVP)**: Pyvis → static HTML export (간단, 의존성 최소)
2. **Phase 4 (Full)**: Dash Cytoscape → interactive dashboard (편집, 필터링)

## Phase 3: HTML Export (Pyvis)

### 기능

```python
tg = ToolGraph()
tg.ingest_openapi("petstore.json")

# HTML 파일 생성
tg.visualize("tool_graph.html")
# → 브라우저에서 열면 Neo4j 스타일 그래프 탐색
```

### 시각 요소

```
노드 색상 (NodeType별):
  Domain   → 🟣 보라 (#9b59b6)
  Category → 🔵 파랑 (#3498db)
  Tool     → 🟢 초록 (#2ecc71)

엣지 색상 (RelationType별):
  REQUIRES        → 🔴 빨강 (실선, 방향)
  PRECEDES        → 🟠 주황 (실선, 방향)
  COMPLEMENTARY   → 🔵 파랑 (점선)
  SIMILAR_TO      → ⚪ 회색 (점선)
  CONFLICTS_WITH  → 🟡 노랑 (파선)
  BELONGS_TO      → ⚫ 검정 (가는 실선)

노드 크기:
  연결 수(degree)에 비례 — hub tool이 더 크게 표시
```

### Progressive Disclosure (1000+ 노드 대응)

```
Level 0: Domain 노드만 표시 (3~10개)
  ↓ 클릭
Level 1: 선택한 Domain의 Category 노드 표시
  ↓ 클릭
Level 2: 선택한 Category의 Tool 노드 + 관계 표시
```

### 구현

```python
# visualization/html_export.py

def export_html(
    tool_graph: ToolGraph,
    output_path: str = "tool_graph.html",
    *,
    layout: str = "force-directed",  # or "hierarchical"
    show_labels: bool = True,
    physics: bool = True,
    progressive: bool = True,  # 1000+ 노드 시 자동 활성화
) -> str:
    """ToolGraph → interactive HTML file."""
    from pyvis.network import Network

    net = Network(height="800px", width="100%", directed=True)
    net.barnes_hut(gravity=-3000)

    # 노드 추가
    for node_id, node_data in tool_graph.graph.nodes():
        ...

    # 엣지 추가
    for source, target, edge_data in tool_graph.graph.edges():
        ...

    net.save_graph(output_path)
    return output_path
```

## Phase 4: Interactive Dashboard (Dash Cytoscape)

### 기능

1. **그래프 탐색**: 줌, 팬, 노드 클릭 상세보기
2. **수동 편집**: 드래그로 관계 추가, 우클릭 삭제
3. **필터링**: relation type, category, confidence 필터
4. **검색 테스트**: 쿼리 입력 → retrieve 결과 하이라이트
5. **관계 검증**: 자동 감지된 관계를 confirm/reject
6. **Import/Export**: JSON 저장·로드, Neo4j export

### 레이아웃

```
┌──────────────────────────────────────────────────────────────┐
│  graph-tool-call Dashboard                     [Save] [Load] │
├──────────┬───────────────────────────────────────────────────┤
│          │                                                   │
│ Filters  │              Graph View                           │
│          │                                                   │
│ □ REQUIRES   │         ┌──────┐                             │
│ □ PRECEDES   │    ┌────┤ pets ├────┐                        │
│ □ COMPLEMENT │    │    └──────┘    │                        │
│ □ SIMILAR    │  ┌─┴──┐         ┌──┴──┐                     │
│ □ CONFLICTS  │  │add │─────────│ get │                     │
│              │  │Pet │ REQUIRES│Pet  │                     │
│ Confidence   │  └────┘         └─────┘                     │
│ [====|===] │                                                │
│ 0.5   1.0  │                                               │
│              │                                               │
│ Categories   │                                               │
│ ☑ pet        │                                               │
│ ☑ store      │                                               │
│ ☑ user       │                                               │
│              │                                               │
├──────────┴───────────────────────────────────────────────────┤
│ Search: [주문 취소하고 환불___________] [Search]             │
│ Results: cancelOrder(0.92), refundPayment(0.85), ...        │
├─────────────────────────────────────────────────────────────┤
│ Node Detail: cancelOrder                                     │
│ Description: 주문을 취소합니다                               │
│ Category: orders                                             │
│ Relations: ← listOrders (PRECEDES)                          │
│            → refundPayment (COMPLEMENTARY)                   │
│ Parameters: orderId (string, required), reason (string)     │
└─────────────────────────────────────────────────────────────┘
```

### Neo4j Export

```python
# visualization/neo4j_export.py

def export_cypher(tool_graph: ToolGraph, output_path: str) -> str:
    """ToolGraph → Cypher CREATE statements."""
    lines = []
    for node_id, data in tool_graph.graph.nodes():
        props = serialize_props(data)
        lines.append(f"CREATE (:{data['type']} {{name: '{node_id}', {props}}})")

    for src, tgt, data in tool_graph.graph.edges():
        lines.append(
            f"MATCH (a {{name: '{src}'}}), (b {{name: '{tgt}'}}) "
            f"CREATE (a)-[:{data['relation_type']}]->(b)"
        )
    return "\n".join(lines)
```

## 구현 범위

| Phase | 작업 | 설명 |
|-------|------|------|
| **3** | Pyvis HTML export | static 그래프 시각화 |
| **3** | Progressive disclosure | 1000+ 노드 계층 탐색 |
| **3** | Neo4j Cypher export | 외부 Neo4j import용 |
| **4** | Dash Cytoscape dashboard | interactive 편집·검증 |
| **4** | 검색 테스트 UI | retrieve 결과 시각화 |
| **4** | 관계 검증 UI | confirm/reject 워크플로우 |
