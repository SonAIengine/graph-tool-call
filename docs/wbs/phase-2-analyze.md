# Phase 2: Analyze + Search Modes + Ontology Modes

**상태**: ⬜ 대기
**목표 기간**: 2주
**선행 조건**: Phase 1 완료

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
| 2-1a | Stage 1-3: hash + name fuzzy + schema Jaccard | `analyze/similarity.py` | ⬜ |
| 2-1b | Stage 4-5: semantic + composite score | `analyze/similarity.py` | ⬜ |
| 2-1c | `find_duplicates()` API | `tool_graph.py` | ⬜ |
| 2-1d | `merge_duplicates()` + MergeStrategy | `tool_graph.py` | ⬜ |

---

### 2-2. Embedding 검색

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-2a | all-MiniLM-L6-v2 / multilingual-e5 연동 | `retrieval/embedding.py` | ⬜ |
| 2-2b | EmbeddingIndex 실제 검색 통합 | `retrieval/embedding.py` | ⬜ |
| 2-2c | RetrievalEngine에 embedding score 연결 | `retrieval/engine.py` | ⬜ |

---

### 2-3. Ontology Modes ← EXPANDED

설계 문서: [design/ontology-modes.md](../design/ontology-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-3a | Auto mode 완성 (embedding clustering) | `ontology/auto.py` | ⬜ |
| **2-3b** | **OntologyLLM 추상화** | `ontology/llm_provider.py` | ⬜ |
| **2-3c** | **Ollama provider** | `ontology/llm_provider.py` | ⬜ |
| **2-3d** | **vLLM provider** | `ontology/llm_provider.py` | ⬜ |
| **2-3e** | **OpenAI compatible provider** | `ontology/llm_provider.py` | ⬜ |
| **2-3f** | **Batch 관계 추론 (50개 단위)** | `ontology/auto.py` | ⬜ |
| **2-3g** | **LLM 카테고리 제안** | `ontology/auto.py` | ⬜ |

**세부 (NEW)**:
- `OntologyLLM` ABC: `infer_relations()`, `suggest_categories()`
- Ollama: `http://localhost:11434/api/generate` 호출
- vLLM: OpenAI compatible endpoint
- OpenAI: GPT-4o-mini / Claude API
- Batch 처리: 50개 tool씩 관계 추론 → confidence score
- 카테고리 제안: tool → category 매핑 JSON 출력

---

### 2-4. Search Modes ← NEW SECTION

설계 문서: [design/search-modes.md](../design/search-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-4a | SearchLLM 추상화 (Ollama/vLLM/OpenAI) | `retrieval/search_llm.py` | ⬜ |
| 2-4b | Tier 1: Query expansion 구현 | `retrieval/engine.py` | ⬜ |
| 2-4c | Tier 2: Intent decomposition 구현 | `retrieval/engine.py` | ⬜ |
| 2-4d | wRRF (weighted RRF) 적응 가중치 | `retrieval/engine.py` | ⬜ |

**세부**:
- `SearchLLM` ABC: `expand_query()`, `decompose_intents()`
- Tier 1: 1.5B~3B 모델로 키워드 확장 + 동의어 + 다국어 번역
- Tier 2: 3B~7B 모델로 복잡한 쿼리를 개별 intent로 분해
- wRRF: query 특성(단순/복합)에 따라 keyword/embedding/graph 가중치 조정

---

### 2-5. Arazzo Specification 지원 ← NEW

설계 문서: [design/call-ordering.md](../design/call-ordering.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-5a | Arazzo spec 파서 | `ingest/arazzo.py` | ⬜ |
| 2-5b | 워크플로우 → PRECEDES 관계 변환 | `ingest/arazzo.py` | ⬜ |

**세부**:
- Arazzo 1.0.0 파싱 (YAML)
- `steps[].dependsOn` → PRECEDES 관계 (confidence 1.0)
- `successCriteria` → 조건부 관계 메타데이터

---

### 2-6. 벤치마크 ← EXPANDED

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 2-6a | Tool set 구성 (Petstore/GitHub/Synthetic) | `benchmarks/` | ⬜ |
| 2-6b | Precision/Recall/NDCG/Workflow Coverage | `benchmarks/` | ⬜ |
| **2-6c** | **Tier별 (0/1/2) Recall/Precision 비교** | `benchmarks/` | ⬜ |
| 2-6d | baseline 비교 결과 정리 | `docs/` | ⬜ |

## 의존 관계

```
Phase 1 완료
  └→ Phase 2 전체

2-2 (Embedding)
  ├→ 2-1b (semantic dedup — embedding 활용)
  ├→ 2-3a (embedding clustering)
  └→ 2-4 (Search Modes — embedding score)

2-3b (OntologyLLM 추상화)
  └→ 2-3c~g (provider 구현 + batch 추론)

2-4a (SearchLLM 추상화)
  └→ 2-4b~c (Tier 1/2 구현)

2-5 (Arazzo) — 독립, 병렬 가능

2-6 (벤치마크) — 모든 작업 완료 후
```
