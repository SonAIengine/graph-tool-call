# Phase 0: Core MVP ✅

**상태**: 완료 (32 tests passing)

## 산출물

| WBS ID | 작업 | 파일 | 상태 |
|--------|------|------|------|
| 0-1 | ToolSchema + 포맷 파서 | `core/tool.py` | ✅ |
| 0-2 | GraphEngine Protocol + NetworkX | `core/protocol.py`, `core/graph.py` | ✅ |
| 0-3 | Ontology schema + builder | `ontology/schema.py`, `ontology/builder.py` | ✅ |
| 0-4 | Retrieval (keyword + graph expansion) | `retrieval/engine.py`, `retrieval/graph_search.py` | ✅ |
| 0-5 | LangChain integration | `langchain/retriever.py`, `langchain/tools.py` | ✅ |
| 0-6 | ToolGraph facade + serialization | `tool_graph.py`, `serialization.py` | ✅ |
| 0-7 | Tests (32 passing) | `tests/` | ✅ |

## 알려진 문제 (Phase 1에서 수정)

| 문제 | 위치 | 원인 |
|------|------|------|
| tags 비어있지 않으면 TypeError | `retrieval/engine.py` | `set.update(generator of lists)` |
| keyword matching 약함 | `retrieval/engine.py` | 단순 token overlap, BM25 아님 |
| embedding 미연결 | `retrieval/embedding.py` | EmbeddingIndex 존재하지만 engine에 연결 안 됨 |
| auto_organize 미구현 | `ontology/auto.py` | NotImplementedError |
