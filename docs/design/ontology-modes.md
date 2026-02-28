# Ontology Building Modes — 설계 문서

**WBS**: 2-3 (Phase 2 확장)
**파일**: `ontology/auto.py`, `ontology/builder.py`, `ontology/llm_provider.py`

## 핵심 구조

온톨로지 **생성 모드**와 **대시보드**는 별개 레이어다.

```
┌─────────────┐     ┌─────────────┐
│  Auto Mode  │     │ LLM-Auto    │
│  (알고리즘)  │     │ (LLM 보조)  │
└──────┬──────┘     └──────┬──────┘
       │                   │
       └───────┬───────────┘
               ▼
        ┌──────────────┐
        │  Tool Graph  │
        └──────┬───────┘
               │
               ▼
    ┌─────────────────────┐
    │  Dashboard (공통)    │
    │  시각화 + 수동 편집  │
    │  관계 검증/수정      │
    └─────────────────────┘
```

- **생성 모드**: 어떻게 온톨로지를 만들 것인가 (Auto / LLM-Auto)
- **대시보드**: 만들어진 결과를 시각화하고 수정하는 공통 도구

## 2가지 생성 모드

```
┌────────────────────────────────────────────────────────────┐
│  Mode 1: Auto (No LLM)                                    │
│  ──────────────────────                                    │
│  알고리즘 기반 자동 구성                                    │
│  → 의존성: 없음 (core만)                                   │
│  → 품질: ★★☆ (structural 관계만)                          │
│  → 속도: ★★★ (즉시)                                      │
├────────────────────────────────────────────────────────────┤
│  Mode 2: LLM-Auto                                          │
│  ────────────────                                          │
│  Auto + LLM으로 관계 추론 · 카테고리 제안 품질 강화         │
│  → 의존성: ollama/vllm/llama.cpp/openai                    │
│  → 품질: ★★★ (semantic 이해)                              │
│  → 속도: ★★☆ (모델에 따라)                                │
└────────────────────────────────────────────────────────────┘
```

## Dashboard (공통 레이어)

어떤 모드로 만들었든, 대시보드에서 동일하게:

1. **시각화** — Neo4j 스타일 그래프 탐색 (줌, 팬, 클릭 상세)
2. **수동 편집** — 관계 추가/삭제, 카테고리 이름 수정, 도메인 계층 조정
3. **검증** — 자동 감지된 관계를 confirm/reject
4. **검색 테스트** — 쿼리 입력 → retrieve 결과 하이라이트
5. **저장/로드** — JSON export/import

### Dashboard 워크플로우

```
1. 생성 모드 실행 (Auto 또는 LLM-Auto)
   tg.auto_organize()              # Auto
   tg.auto_organize(llm=llm)       # LLM-Auto

2. 대시보드 열기
   tg.dashboard(port=8050)
   # → http://localhost:8050

3. 시각화 확인 + 수동 수정
   - 잘못된 관계 삭제
   - 누락된 관계 추가
   - 카테고리 이름 수정
   - LLM이 제안한 관계 검증

4. 저장
   tg.save("tool_graph.json")

# 또는 static HTML export (대시보드 없이)
tg.visualize("graph.html")
```

### 수동 편집 API (코드로도 가능)

대시보드 없이 코드로 직접 편집도 가능:

```python
# 카테고리 추가
tg.add_category("payment", domain="commerce")

# 관계 추가
tg.add_relation("createOrder", "processPayment", "requires")
tg.add_relation("listOrders", "cancelOrder", "precedes")

# 관계 삭제
tg.remove_relation("addPet", "deletePet", "conflicts_with")

# 카테고리 할당
tg.assign_category("createOrder", "orders")
```

## Mode 1: Auto (No LLM)

LLM 없이 순수 알고리즘으로 ontology 구성. **기본 모드**.

### 방법

```python
tg = ToolGraph()
tg.ingest_openapi("petstore.json")
tg.auto_organize()  # LLM 없이 동작

# 내부 동작:
# 1. Tag/path 기반 카테고리 생성
# 2. CRUD 패턴 → REQUIRES, COMPLEMENTARY
# 3. $ref 공유 → COMPLEMENTARY
# 4. Path hierarchy → REQUIRES
# 5. Response-parameter 매칭 → REQUIRES
# 6. State machine → PRECEDES
# 7. CRUD workflow ordering → PRECEDES
```

### 카테고리 자동 생성 전략

```
우선순위:
1. OpenAPI tags 사용 (있으면)
2. Path prefix 분석 (/pets/... → "pets" 카테고리)
3. Embedding clustering (optional, sentence-transformers 있으면)
```

### Embedding Clustering (LLM 없이도 semantic 그룹핑)

```python
def cluster_tools(tools: list[ToolSchema], n_clusters: int | None = None):
    """sentence-transformers로 tool description을 임베딩 → K-means 클러스터링."""
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans

    model = SentenceTransformer("all-MiniLM-L6-v2")
    descriptions = [t.description for t in tools]
    embeddings = model.encode(descriptions)

    if n_clusters is None:
        n_clusters = max(3, len(tools) // 10)  # 자동 결정

    kmeans = KMeans(n_clusters=n_clusters)
    labels = kmeans.fit_predict(embeddings)

    # 각 cluster의 대표 키워드로 category 이름 생성
    return assign_cluster_names(tools, labels, embeddings)
```

## Mode 2: LLM-Auto

Auto의 모든 것 + LLM을 활용하여 더 정확한 관계 추론.

### 워크플로우

```
1. Auto mode로 structural 관계 감지 (확실한 것)
2. LLM에게 나머지 tool 쌍에 대해 관계 추론 요청
3. LLM 결과를 confidence score와 함께 추가
4. Dashboard에서 결과 확인 + 수정
```

### LLM Provider 추상화

```python
from abc import ABC, abstractmethod

class OntologyLLM(ABC):
    """온톨로지 구성용 LLM 인터페이스."""

    @abstractmethod
    def infer_relations(
        self,
        tools: list[ToolSummary],
        batch_size: int = 50,
    ) -> list[InferredRelation]:
        """tool 쌍 간 관계를 추론."""

    @abstractmethod
    def suggest_categories(
        self,
        tools: list[ToolSummary],
    ) -> dict[str, list[str]]:
        """tool → category 매핑 제안."""

# --- Provider 구현 ---

class OllamaOntologyLLM(OntologyLLM):
    """Ollama 로컬 모델 (Qwen2.5, Llama3, Mistral 등)."""
    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
    ): ...

class VLLMOntologyLLM(OntologyLLM):
    """vLLM 서버."""
    def __init__(self, model: str, base_url: str): ...

class LlamaCppOntologyLLM(OntologyLLM):
    """llama.cpp (llama-cpp-python 바인딩)."""
    def __init__(self, model_path: str): ...

class OpenAIOntologyLLM(OntologyLLM):
    """OpenAI API 호환 (GPT, Claude 등)."""
    def __init__(self, api_key: str, model: str, base_url: str | None = None): ...
```

### Prompt 설계

#### 관계 추론 (Batch)

```
You are an API relationship analyzer. Given a list of API tools,
identify relationships between them.

Tools:
1. createUser - Creates a new user account (POST /users)
2. getUser - Gets user by ID (GET /users/{userId})
3. listOrders - Lists orders for a user (GET /users/{userId}/orders)
4. cancelOrder - Cancels an order (POST /orders/{orderId}/cancel)
5. processRefund - Processes a refund (POST /refunds)

For each pair with a relationship, output JSON:
[
  {"source": "createUser", "target": "getUser",
   "relation": "REQUIRES", "reason": "getUser needs userId from createUser"},
  ...
]

Relation types: REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH
```

#### 카테고리 추론

```
Group these API tools into logical categories.

Tools:
{tools_list}

Output JSON:
{
  "categories": {
    "user_management": ["createUser", "getUser", "updateUser"],
    "order_processing": ["createOrder", "cancelOrder", "listOrders"],
    ...
  }
}
```

### Batch 처리

```python
def auto_organize_with_llm(
    tg: ToolGraph,
    llm: OntologyLLM,
    batch_size: int = 50,
    min_confidence: float = 0.7,
):
    """LLM 기반 자동 온톨로지 구성."""
    tools = list(tg.get_all_tools())

    # 1. 먼저 auto mode로 structural 관계 (확실한 것)
    tg.auto_organize()

    # 2. LLM으로 추가 관계 추론 (50개씩 batch)
    for batch in chunked(tools, batch_size):
        relations = llm.infer_relations(batch)
        for rel in relations:
            if rel.confidence >= min_confidence:
                tg.add_relation(
                    rel.source, rel.target, rel.relation_type,
                    metadata={"source": "llm", "confidence": rel.confidence}
                )

    # 3. LLM으로 카테고리 제안
    categories = llm.suggest_categories(tools)
    for cat_name, tool_names in categories.items():
        tg.add_category(cat_name)
        for tool_name in tool_names:
            tg.assign_category(tool_name, cat_name)
```

### 모델 사이즈 가이드

| Task | 최소 모델 | 추천 모델 |
|------|----------|----------|
| 관계 추론 (5-10 tools) | 3B | Qwen2.5-7B |
| 관계 추론 (50 tools batch) | 7B | Qwen2.5-14B / GPT-4o-mini |
| 카테고리 분류 | 3B | Qwen2.5-7B |
| 복잡한 도메인 분석 | 14B+ | GPT-4o / Claude |

## API 사용 예시

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("api-spec.json")

# Mode 1: Auto (기본, LLM 없음)
tg.auto_organize()

# Mode 2: LLM-Auto
from graph_tool_call.ontology import OllamaOntologyLLM
llm = OllamaOntologyLLM(model="qwen2.5:7b")
tg.auto_organize(llm=llm)  # LLM 전달하면 자동으로 LLM-Auto

# 또는 OpenAI API
from graph_tool_call.ontology import OpenAIOntologyLLM
llm = OpenAIOntologyLLM(api_key="...", model="gpt-4o-mini")
tg.auto_organize(llm=llm)

# 어떤 모드든 → Dashboard에서 시각화 + 수정
tg.dashboard(port=8050)

# 또는 static HTML export
tg.visualize("graph.html")
```

## 구현 범위

| Phase | 작업 | 설명 |
|-------|------|------|
| **1** | Auto mode 기본 (tag/path/CRUD) | LLM 없이 동작 |
| **2** | Embedding clustering | sentence-transformers 카테고리 |
| **2** | OntologyLLM 추상화 | Provider 인터페이스 |
| **2** | Ollama/vLLM provider | 로컬 모델 연동 |
| **2** | OpenAI compatible provider | 클라우드 모델 연동 |
| **2** | Batch 관계 추론 | 50개 단위 처리 |
| **3** | llama.cpp provider | 최경량 로컬 추론 |
| **3** | Dashboard (Pyvis → Dash Cytoscape) | 시각화 + 수동 편집 (공통) |
| **3** | 관계 검증 UI | confirm/reject (공통) |
