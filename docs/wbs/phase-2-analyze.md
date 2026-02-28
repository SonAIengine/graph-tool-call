# Phase 2: Deduplication + Embedding + Auto-organize

**상태**: ⬜ 대기
**목표 기간**: 2주
**선행 조건**: Phase 1 완료

## 완료 기준

```python
tg.ingest_openapi("./user-api.json")
tg.ingest_openapi("./order-api.json")
dupes = tg.find_duplicates()              # cross-API 중복 감지
tg.auto_organize(llm=llm)                 # LLM 자동 관계 구성
tools = tg.retrieve("사용자 주문 조회")    # 한국어 동작 (embedding)
```

## WBS 상세

### 2-1. Deduplication Pipeline

설계 문서: [design/deduplication.md](../design/deduplication.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-1a | Stage 1-3: hash + name fuzzy + schema Jaccard | `analyze/similarity.py` | ⬜ |
| 2-1b | Stage 4-5: semantic + composite score | `analyze/similarity.py` | ⬜ |
| 2-1c | `find_duplicates()` API | `tool_graph.py` | ⬜ |
| 2-1d | `merge_duplicates()` + MergeStrategy | `tool_graph.py` | ⬜ |

---

### 2-2. Embedding 검색

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-2a | all-MiniLM-L6-v2 연동 | `retrieval/embedding.py` | ⬜ |
| 2-2b | EmbeddingIndex 실제 검색 통합 | `retrieval/embedding.py` | ⬜ |
| 2-2c | RetrievalEngine에 embedding score 연결 | `retrieval/engine.py` | ⬜ |

---

### 2-3. Auto-organize

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-3a | LLM 기반 자동 온톨로지 (50개 batch) | `ontology/auto.py` | ⬜ |
| 2-3b | embedding clustering fallback | `ontology/auto.py` | ⬜ |

---

### 2-4. bigtool 연동

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-4a | retrieve_tools_function adapter | `integrations/bigtool.py` | ⬜ |
| 2-4b | examples/bigtool_plugin.py | `examples/bigtool_plugin.py` | ⬜ |

---

### 2-5. 벤치마크

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-5a | Tool set 구성 (Petstore/GitHub/Synthetic) | `benchmarks/` | ⬜ |
| 2-5b | Precision/Recall/NDCG/Workflow Coverage | `benchmarks/` | ⬜ |
| 2-5c | baseline 비교 결과 정리 | `docs/` | ⬜ |
