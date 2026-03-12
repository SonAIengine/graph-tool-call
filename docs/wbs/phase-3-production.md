# Phase 3: Production + Visualization

**상태**: 🟨 대부분 완료
**목표 기간**: 2주
**선행 조건**: Phase 2 완료

> 2026-03 기준 실제 코드 상태를 반영했다.
> Phase 3의 핵심 산출물인 CLI, conflict detection, visualization export,
> model-driven search, commerce preset은 구현되어 있다.
> 다만 문서 초안에 있던 `MCP server ingest`와 `llama.cpp provider`,
> `PyPI 배포`는 아직 별도 후속 작업으로 남아 있다.

## 완료 기준

```python
tg = ToolGraph()

# MCP tool list ingest
tg.ingest_mcp_tools(mcp_tools, server_name="example")

# Visualization
tg.export_html("graph.html")     # Pyvis HTML / standalone HTML
tg.export_cypher("graph.cypher") # Neo4j import용
tg.export_graphml("graph.graphml")

# Model-Driven Search
tools = tg.search_api.search_tools("payment processing", top_k=5)
workflow = tg.search_api.get_workflow("cancelOrder")
# → ["listOrders", "getOrder", "cancelOrder", "processRefund"]

# CLI
# $ graph-tool-call ingest petstore.json -o graph.json
# $ graph-tool-call retrieve "add a pet" --top-k 5
```

## WBS 상세

### 3-1. MCP Server Ingest

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-1a | MCP server discovery + tool listing | `ingest/mcp.py` | ⬜ |
| 3-1b | MCP tool → ToolSchema 변환 | `ingest/mcp.py` | ✅ |

현재 상태:
- `ingest_mcp_tools()`와 `ingest/mcp.py`의 MCP tool list → `ToolSchema` 변환은 구현됨
- MCP 서버 URL에 직접 연결해 discovery/listing 하는 `ingest_mcp(...)` 형태의 API는 아직 없음

---

### 3-2. Conflict Detection 강화

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-2a | CONFLICTS_WITH 자동 감지 강화 | `analyze/conflict.py` | ✅ |
| 3-2b | 동일 리소스 write 충돌 감지 | `analyze/conflict.py` | ✅ |

---

### 3-3. CLI

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-3a | `ingest` 명령 (spec → graph.json) | `__main__.py` | ✅ |
| 3-3b | `analyze` 명령 (관계 분석 리포트) | `__main__.py` | ✅ |
| 3-3c | `retrieve` 명령 (쿼리 → tool 목록) | `__main__.py` | ✅ |
| 3-3d | `visualize` 명령 (graph → HTML/GraphML/Cypher) | `__main__.py` | ✅ |
| 3-3e | `info` 명령 (그래프 요약) | `__main__.py` | ✅ |

---

### 3-4. Visualization — Static HTML ← EXPANDED

설계 문서: [design/visualization-dashboard.md](../design/visualization-dashboard.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-4a | Pyvis HTML export | `visualization/html_export.py` | ✅ |
| 3-4b | Progressive disclosure (1000+ 노드) | `visualization/html_export.py` | ✅ |
| **3-4c** | **Neo4j Cypher export** | `visualization/cypher_export.py` | ✅ |
| **3-4d** | **GraphML export** | `visualization/graphml_export.py` | ✅ |

**3-4a 세부**:
- NodeType별 색상: Domain(보라), Category(파랑), Tool(초록)
- RelationType별 엣지 스타일: REQUIRES(빨강 실선), PRECEDES(주황 실선), etc.
- 노드 크기: degree 비례
- Physics engine: barnes_hut

**3-4b 세부**:
- Level 0: Domain만 → 클릭 → Level 1: Category → 클릭 → Level 2: Tool
- 1000+ 노드도 단계적 탐색 가능

**3-4c 세부 (NEW)**:
- `CREATE` statement 생성 (노드 + 관계)
- Neo4j Browser에서 직접 import 가능

**3-4d 세부 (NEW)**:
- NetworkX의 `nx.write_graphml()` 활용
- Gephi, yEd 등 외부 도구에서 열기 가능

---

### 3-5. Model-Driven Search 완성 ← NEW

설계 문서: [design/search-modes.md](../design/search-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-5a | search_tools LLM tool 노출 | `retrieval/model_driven.py` | ✅ |
| 3-5b | get_workflow 워크플로우 조회 | `retrieval/model_driven.py` | ✅ |
| 3-5c | browse_categories 트리 조회 | `retrieval/model_driven.py` | ✅ |

**세부**:
- `ToolGraphSearchAPI`의 메서드를 LLM function calling tool로 노출
- `get_workflow()`: PRECEDES 관계를 따라 워크플로우 체인 반환
- LLM-friendly JSON 응답 포맷

---

### 3-6. llama.cpp Provider ← NEW

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-6a | LlamaCppOntologyLLM | `ontology/llm_provider.py` | ⬜ |
| 3-6b | LlamaCppSearchLLM | `retrieval/search_llm.py` | ⬜ |

**세부**:
- `llama-cpp-python` 바인딩 활용
- GGUF 모델 직접 로드 (GPU 없이도 동작)

참고:
- OpenAI-compatible endpoint를 통한 연동 경로는 이미 있음
- 그러나 `LlamaCpp...` 이름의 전용 provider 클래스는 아직 없음

---

### 3-7. 커머스 도메인 프리셋 ← NEW

설계 문서: [design/call-ordering.md](../design/call-ordering.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-7a | 주문/결제/배송 워크플로우 템플릿 | `presets/commerce.py` | ✅ |
| 3-7b | 커머스 도메인 자동 감지 | `presets/commerce.py` | ✅ |

**세부**:
- 커머스 API 패턴 인식: 주문 라이프사이클, 결제 플로우, 배송 상태
- 도메인 특화 PRECEDES 패턴 적용 (confidence 부스트)

---

### 3-8. GitHub Actions CI ✅

이미 완료: `.github/workflows/ci.yml`

---

### 3-9. PyPI 배포

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 3-9a | pyproject.toml extras 정리 | `pyproject.toml` | ⬜ |
| 3-9b | PyPI 업로드 (poetry publish) | - | ⬜ |
| 3-9c | GitHub Release 생성 | - | ⬜ |

## 현재 정리

- 완료:
  - conflict detection
  - CLI (`ingest`, `analyze`, `retrieve`, `visualize`, `info`)
  - HTML/GraphML/Cypher export
  - model-driven search API
  - commerce preset
- 부분 완료:
  - MCP ingest: tool list ingest는 완료, server discovery는 미구현
- 미완료:
  - llama.cpp 전용 provider
  - PyPI 배포 절차
