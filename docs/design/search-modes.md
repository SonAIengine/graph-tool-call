# Search Modes — 설계 문서

**WBS**: 1-7 (Phase 1 확장), 2-2 (Phase 2 확장)
**파일**: `retrieval/engine.py`, `retrieval/keyword.py`, `retrieval/embedding.py`
**리서치**: Agent-as-a-Graph (KG+vector+wRRF), AutoTool (transition graph)

## 설계 원칙

1. **LLM 없이 동작하는 것이 기본** — BM25 + graph traversal만으로 검색 가능
2. **LLM 있으면 품질 향상** — query expansion, intent decomposition
3. **아주 작은 모델도 활용 가능** — 1.5B~3B 모델로도 검색 쿼리 개선
4. **두 가지 모드**: pre-query (사전 검색) + model-driven (모델이 직접 검색)

## 3-Tier 검색 아키텍처

```
┌────────────────────────────────────────────────────────┐
│  Tier 0: No-LLM (기본)                                │
│  ─────────────────────                                 │
│  BM25 keyword matching + graph expansion               │
│  → 의존성: 없음                                        │
│  → 성능: baseline                                      │
│  → 지연: <50ms (500 tools)                             │
├────────────────────────────────────────────────────────┤
│  Tier 1: Small-LLM Enhanced (선택)                     │
│  ──────────────────────────────                        │
│  Tier 0 + query expansion + keyword extraction         │
│  → 모델: Qwen2.5-1.5B ~ Phi-3-3B (Ollama/vLLM)       │
│  → 추가 지연: ~200ms (로컬 GPU)                       │
│  → 개선: Recall +15~25%                               │
├────────────────────────────────────────────────────────┤
│  Tier 2: Full-LLM (선택)                               │
│  ────────────────────                                  │
│  Tier 1 + intent decomposition + iterative refinement  │
│  → 모델: GPT-4o / Claude / Qwen2.5-7B+                │
│  → 추가 지연: ~500ms~2s                               │
│  → 개선: Recall +30~40%, Workflow Coverage +50%        │
└────────────────────────────────────────────────────────┘
```

## Mode 1: Pre-Query Search (사전 검색)

AI 모델에 input이 전달되기 전, 사용자 입력으로 tool 후보를 검색.

```
사용자 입력: "주문을 취소하고 환불해줘"
        │
        ▼
┌─ Pre-Query Search ─────────────────────────────┐
│                                                 │
│  [Tier 0] BM25 + Graph                         │
│  tokens: ["주문", "취소", "환불"]               │
│  → cancelOrder (0.82)                           │
│  → graph expand: listOrders (PRECEDES, 0.7)    │
│  → refundPayment (0.75)                        │
│                                                 │
│  [Tier 1] Query Expansion (LLM optional)       │
│  expanded: ["주문", "취소", "환불",             │
│             "order", "cancel", "refund",        │
│             "payment", "return"]                │
│  → processRefund (0.68) ← 새로 발견!           │
│                                                 │
│  [Tier 2] Intent Decomposition (LLM optional)  │
│  intents: [                                     │
│    "주문 조회" → listOrders, getOrder           │
│    "주문 취소" → cancelOrder                    │
│    "환불 처리" → refundPayment, processRefund   │
│  ]                                              │
│  → 통합: top_k=5 반환                          │
└────────────────────────────────────────────────┘
        │
        ▼
  Agent LLM에 tool list 전달
```

### Pre-Query Pipeline 구현

```python
class SearchMode(str, Enum):
    BASIC = "basic"          # Tier 0 only
    ENHANCED = "enhanced"    # Tier 0 + Tier 1
    FULL = "full"            # Tier 0 + Tier 1 + Tier 2

class RetrievalEngine:
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        mode: SearchMode = SearchMode.BASIC,
        llm: BaseLLM | None = None,
    ) -> list[ToolSchema]:
        # Tier 0: Always run
        keyword_scores = self.bm25_score(query)
        graph_scores = self.graph_expand(keyword_scores, top_k=top_k)
        results = self.rrf_fuse([keyword_scores, graph_scores])

        if mode >= SearchMode.ENHANCED and llm:
            # Tier 1: Query expansion
            expanded = llm.expand_query(query)
            expanded_scores = self.bm25_score(expanded)
            results = self.rrf_fuse([results, expanded_scores])

        if mode >= SearchMode.FULL and llm:
            # Tier 2: Intent decomposition
            intents = llm.decompose_intents(query)
            for intent in intents:
                intent_scores = self.bm25_score(intent)
                results = self.rrf_fuse([results, intent_scores])

        return self.top_k(results, k=top_k)
```

## Mode 2: Model-Driven Search (모델 직접 검색)

Agent LLM이 직접 tool graph를 검색할 수 있는 인터페이스.

```
Agent LLM
  │
  ├─ "search_tools" function call
  │   → query: "payment processing"
  │   → filters: {"category": "payment", "relation": "PRECEDES"}
  │   → top_k: 5
  │
  ├─ "browse_categories" function call
  │   → 카테고리 트리 반환
  │
  ├─ "get_related_tools" function call
  │   → tool_name: "createPayment"
  │   → relation_type: "PRECEDES"
  │   → depth: 2
  │
  └─ "get_tool_details" function call
      → tool_name: "capturePayment"
      → 상세 파라미터 반환
```

### Model-Driven API

```python
class ToolGraphSearchAPI:
    """Agent LLM이 직접 호출할 수 있는 검색 API.
    각 메서드를 LLM tool로 노출."""

    def search_tools(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        relation_filter: str | None = None,
    ) -> list[ToolSummary]:
        """자연어로 tool 검색."""

    def browse_categories(self) -> dict[str, list[str]]:
        """Domain → Category 트리 반환."""

    def get_related_tools(
        self,
        tool_name: str,
        relation_type: str | None = None,
        depth: int = 1,
    ) -> list[RelatedTool]:
        """특정 tool의 관련 tool 조회."""

    def get_tool_details(self, tool_name: str) -> ToolSchema:
        """tool 상세 정보 반환."""

    def get_workflow(self, tool_name: str) -> list[str]:
        """PRECEDES 관계를 따라 워크플로우 체인 반환."""
```

### LLM-friendly 응답 포맷

```json
{
  "tools": [
    {
      "name": "cancelOrder",
      "description": "주문 취소",
      "category": "orders",
      "precedes": ["refundPayment"],
      "preceded_by": ["getOrder", "listOrders"],
      "related": ["updateOrder", "getOrderStatus"]
    }
  ],
  "workflow_hint": "listOrders → getOrder → cancelOrder → refundPayment"
}
```

## LLM Provider 통합

### Prompt 템플릿

#### Tier 1: Query Expansion (1.5B~3B 모델용)

```
Given a user query, extract search keywords and synonyms.

Query: "{query}"

Output JSON:
{
  "keywords": ["keyword1", "keyword2"],
  "synonyms": ["syn1", "syn2"],
  "english": ["english_term1", "english_term2"]
}
```

#### Tier 2: Intent Decomposition (3B~7B 모델용)

```
Break down the user's request into individual tool-level intents.

Query: "{query}"

Output JSON:
{
  "intents": [
    {"action": "조회", "target": "주문 목록"},
    {"action": "취소", "target": "주문"},
    {"action": "처리", "target": "환불"}
  ]
}
```

### Provider 추상화

```python
from abc import ABC, abstractmethod

class SearchLLM(ABC):
    """검색 보조 LLM 인터페이스."""

    @abstractmethod
    def expand_query(self, query: str) -> str:
        """Tier 1: 키워드 확장."""

    @abstractmethod
    def decompose_intents(self, query: str) -> list[str]:
        """Tier 2: 의도 분해."""

class OllamaSearchLLM(SearchLLM):
    """Ollama 로컬 모델."""
    def __init__(self, model: str = "qwen2.5:1.5b", base_url: str = "http://localhost:11434"):
        ...

class VLLMSearchLLM(SearchLLM):
    """vLLM 서버."""
    def __init__(self, model: str, base_url: str):
        ...

class OpenAICompatibleSearchLLM(SearchLLM):
    """OpenAI API 호환 (GPT, Claude 등)."""
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        ...
```

## 최소 모델 사이즈 가이드

리서치 결과 기반:

| Task | 최소 모델 | 추천 모델 | 비고 |
|------|----------|----------|------|
| Keyword extraction | 1.5B | Qwen2.5-1.5B | 단순 토큰 추출 |
| Query expansion | 3B | Phi-3-mini (3.8B) | 동의어/번역 |
| Intent decomposition | 3B~7B | Qwen2.5-3B~7B | 복잡한 쿼리 분해 |
| JSON structured output | 3B+ | Qwen2.5-3B | JSON 포맷 준수 |
| Semantic reranking | 7B+ | Qwen2.5-7B | 의미 기반 재정렬 |

## 구현 범위

| Phase | 작업 | 설명 |
|-------|------|------|
| **1** | Tier 0 완성 | BM25 + graph + RRF (LLM 없이 동작) |
| **1** | SearchMode enum | BASIC/ENHANCED/FULL 모드 정의 |
| **1** | Model-Driven API 스켈레톤 | search_tools, browse_categories 기본 구현 |
| **2** | Tier 1 구현 | Query expansion + embedding |
| **2** | SearchLLM 추상화 | Ollama/vLLM/OpenAI provider |
| **2** | Tier 2 구현 | Intent decomposition |
| **3** | Model-Driven tools 완성 | LLM tool로 노출, workflow 조회 |
| **3** | 벤치마크 | Tier별 Recall/Precision 비교 |
