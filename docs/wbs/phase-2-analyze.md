# Phase 2: Analyze + Search Modes + Ontology Modes

**상태**: ✅ 완료
**완료일**: 2026-03-01
**테스트**: 179개 통과 (기존 88 + 새 91)

## 완료 기준

```python
tg = ToolGraph()
tg.ingest_openapi("./user-api.json")
tg.ingest_openapi("./order-api.json")

# Deduplication
dupes = tg.find_duplicates()
# → [("user_service.get_user", "order_service.fetch_user", 0.92)]
tg.merge_duplicates(dupes, strategy="keep_best")

# Ontology Mode 1: Auto (LLM 없이)
tg.auto_organize()

# Ontology Mode 3: LLM-Enhanced
from graph_tool_call.ontology import OllamaOntologyLLM
llm = OllamaOntologyLLM(model="qwen2.5:7b")
tg.auto_organize(llm=llm)

# Search Mode: Enhanced (Small LLM)
from graph_tool_call.retrieval import OllamaSearchLLM
search_llm = OllamaSearchLLM(model="qwen2.5:1.5b")
tools = tg.retrieve("사용자 주문 조회", top_k=5, mode="enhanced", llm=search_llm)

# Arazzo workflow
tg.ingest_arazzo("workflow.yaml")
```

> Note: bigtool 연동은 하지 않음. 독립적 라이브러리로 운영.

## WBS 상세

### 2-1. Deduplication Pipeline

설계 문서: [design/deduplication.md](../design/deduplication.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-1a | Stage 1-3: hash + name fuzzy + schema Jaccard | `analyze/similarity.py` | ✅ |
| 2-1b | Stage 4-5: semantic + composite score | `analyze/similarity.py` | ✅ |
| 2-1c | `find_duplicates()` API | `tool_graph.py` | ✅ |
| 2-1d | `merge_duplicates()` + MergeStrategy | `tool_graph.py` | ✅ |

---

### 2-2. Embedding 검색

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-2a | all-MiniLM-L6-v2 연동 (sentence-transformers) | `retrieval/embedding.py` | ✅ |
| 2-2b | EmbeddingIndex: build_from_tools(), encode() | `retrieval/embedding.py` | ✅ |
| 2-2c | RetrievalEngine에 embedding score 연결 | `retrieval/engine.py` | ✅ |

---

### 2-3. Ontology Modes

설계 문서: [design/ontology-modes.md](../design/ontology-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-3a | Auto mode 완성 (tag/domain/embedding clustering) | `ontology/auto.py` | ✅ |
| 2-3b | OntologyLLM 추상화 | `ontology/llm_provider.py` | ✅ |
| 2-3c | Ollama provider | `ontology/llm_provider.py` | ✅ |
| 2-3d | OpenAI compatible provider | `ontology/llm_provider.py` | ✅ |
| 2-3e | Batch 관계 추론 (50개 단위) | `ontology/auto.py` | ✅ |
| 2-3f | LLM 카테고리 제안 | `ontology/auto.py` | ✅ |

---

### 2-4. Search Modes

설계 문서: [design/search-modes.md](../design/search-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-4a | SearchLLM 추상화 (Ollama/OpenAI) | `retrieval/search_llm.py` | ✅ |
| 2-4b | Tier 1: Query expansion 구현 | `retrieval/engine.py` | ✅ |
| 2-4c | Tier 2: Intent decomposition 구현 | `retrieval/engine.py` | ✅ |
| 2-4d | wRRF (weighted RRF) 구현 | `retrieval/engine.py` | ✅ |

---

### 2-5. Arazzo Specification 지원

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-5a | Arazzo spec 파서 | `ingest/arazzo.py` | ✅ |
| 2-5b | 워크플로우 → PRECEDES 관계 변환 | `ingest/arazzo.py` | ✅ |

---

### 2-6. 벤치마크

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-6a | Petstore/Synthetic 데이터셋 | `benchmarks/datasets.py` | ✅ |
| 2-6b | Precision/Recall/NDCG/Workflow Coverage | `benchmarks/metrics.py` | ✅ |
| 2-6c | Tier별 (0/1/2) 비교 실행 스크립트 | `benchmarks/run_benchmark.py` | ✅ |
| 2-6d | metrics 단위 테스트 | `tests/test_benchmark_metrics.py` | ✅ |

## 의존 관계

```
Phase 1 완료
  └→ Phase 2 전체 ✅

2-2 (Embedding) ✅
  ├→ 2-1b (semantic dedup) ✅
  ├→ 2-3a (embedding clustering) ✅
  └→ 2-4 (Search Modes) ✅

2-3b (OntologyLLM 추상화) ✅
  └→ 2-3c~f (provider + batch 추론) ✅

2-4a (SearchLLM 추상화) ✅
  └→ 2-4b~c (Tier 1/2) ✅

2-5 (Arazzo) ✅

2-6 (벤치마크) ✅
```
