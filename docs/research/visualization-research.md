# Tool Graph Visualization 리서치

## 동기

수동 온톨로지 편집을 위한 Neo4j 스타일 대시보드 구현.
1000+ 노드도 탐색 가능해야 함.

## 라이브러리 상세 비교

### Pyvis

- **기반**: vis.js (JavaScript)
- **방식**: Python에서 그래프 생성 → HTML 파일 export
- **장점**: 의존성 최소, 코드 3줄로 시각화, Physics 엔진 내장
- **단점**: 편집 불가 (view only), 500+ 노드 성능 저하
- **설치**: `pip install pyvis`

```python
from pyvis.network import Network

net = Network(height="800px", directed=True)
net.add_node("addPet", label="addPet", color="#2ecc71")
net.add_node("getPet", label="getPet", color="#2ecc71")
net.add_edge("addPet", "getPet", title="REQUIRES", color="#e74c3c")
net.barnes_hut(gravity=-3000)
net.save_graph("graph.html")
```

### Cytoscape.js

- **기반**: 독립 JavaScript 라이브러리
- **방식**: 브라우저에서 직접 렌더링
- **장점**: 5000+ 노드 처리, 풍부한 레이아웃 (dagre, cola, cose), 이벤트 처리
- **단점**: Python 통합 직접 구현 필요
- **선택 레이아웃**: dagre (계층형, DAG에 최적)

### Dash Cytoscape

- **기반**: Cytoscape.js + Plotly Dash
- **방식**: Python callback으로 인터랙션 처리
- **장점**: Cytoscape.js 성능 + Python 생태계, 실시간 편집 가능
- **단점**: Dash 의존성
- **설치**: `pip install dash-cytoscape`

```python
import dash_cytoscape as cyto
from dash import Dash, html, Input, Output

app = Dash(__name__)
app.layout = html.Div([
    cyto.Cytoscape(
        id='graph',
        elements=[
            {'data': {'id': 'addPet', 'label': 'addPet'}, 'classes': 'tool'},
            {'data': {'source': 'addPet', 'target': 'getPet', 'label': 'REQUIRES'}},
        ],
        layout={'name': 'dagre'},
        stylesheet=[
            {'selector': '.tool', 'style': {'background-color': '#2ecc71'}},
            {'selector': 'edge', 'style': {'line-color': '#e74c3c'}},
        ],
    )
])
```

### Streamlit (streamlit-agraph)

- **방식**: Streamlit component
- **장점**: 가장 쉬운 대시보드 구축
- **단점**: 200 노드 이상 느림, 편집 제한적
- **설치**: `pip install streamlit-agraph`

## 대규모 그래프 처리 전략

### Progressive Disclosure (계층 탐색)

```
초기 화면: Domain 노드만 (3~10개)
  │
  ├── [Commerce] ← 클릭
  │     ├── [Orders]    ← 클릭
  │     │     ├── createOrder
  │     │     ├── getOrder
  │     │     ├── cancelOrder
  │     │     └── (관계 엣지 표시)
  │     ├── [Payments]
  │     └── [Products]
  │
  ├── [Users]
  └── [Inventory]
```

### Viewport Culling

화면에 보이는 영역의 노드만 렌더링:
- Cytoscape.js의 `cy.extent()` 활용
- 줌 레벨에 따라 상세도 조절

### Clustering

많은 카테고리의 tool을 그룹 노드로 축약:
- 10개 이상 tool이 있는 카테고리 → compound node
- 클릭하면 expand

## Neo4j Export

### Cypher 생성

```cypher
// 노드 생성
CREATE (:Tool {name: 'addPet', description: 'Add a new pet', category: 'pets'})
CREATE (:Tool {name: 'getPet', description: 'Find pet by ID', category: 'pets'})
CREATE (:Category {name: 'pets', domain: 'petstore'})

// 관계 생성
MATCH (a:Tool {name: 'addPet'}), (b:Tool {name: 'getPet'})
CREATE (a)-[:REQUIRES {confidence: 0.95}]->(b)

MATCH (a:Tool {name: 'addPet'}), (c:Category {name: 'pets'})
CREATE (a)-[:BELONGS_TO]->(c)
```

### GraphML Export

```xml
<graphml>
  <graph edgedefault="directed">
    <node id="addPet">
      <data key="label">addPet</data>
      <data key="type">tool</data>
    </node>
    <edge source="addPet" target="getPet">
      <data key="relation">REQUIRES</data>
    </edge>
  </graph>
</graphml>
```

NetworkX의 `nx.write_graphml()` 직접 활용 가능.

## 결정

| Phase | 구현 | 라이브러리 |
|-------|------|----------|
| **3** | Static HTML export | Pyvis |
| **3** | Neo4j Cypher export | 직접 구현 |
| **3** | GraphML export | NetworkX 내장 |
| **4** | Interactive dashboard | Dash Cytoscape |
| **4** | 수동 편집 UI | Dash callback |
| **4** | Progressive disclosure | Cytoscape.js compound nodes |

## 참고

- [Pyvis Documentation](https://pyvis.readthedocs.io/)
- [Cytoscape.js](https://js.cytoscape.org/)
- [Dash Cytoscape](https://dash.plotly.com/cytoscape)
- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/)
