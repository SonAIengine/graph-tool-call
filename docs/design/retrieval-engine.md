# Retrieval Engine — 설계 문서

**WBS**: 1-7, 2-2, 2.5
**파일**: `retrieval/engine.py`, `retrieval/keyword.py`, `retrieval/embedding.py`, `retrieval/intent.py`, `retrieval/annotation_scorer.py`

## Hybrid 검색 파이프라인 (4-source wRRF)

```
Query: "사용자 파일을 읽고 DB에 저장해줘"
  │
  ├─ [0] Query Augmentation
  │   history context 추가 + Korean normalization
  │
  ├─ [1] BM25-style Keyword Score
  │   tokenize (camelCase split + stem + Korean bigram)
  │   auto-stopword (DF threshold 70%, CRUD verbs 보호)
  │   name subsequence boost (1.5x)
  │   → read_file: 0.42, write_file: 0.15, query_db: 0.38
  │
  ├─ [2] Multi-Layer Seed Building
  │   Layer 1: BM25 top-10
  │   Layer 2: Annotation match top-3 (score > 0.7, intent-matching)
  │   Layer 3: Embedding top-5 (semantic gap 보완)
  │   Layer 4: History seeds
  │   → 최대 15~20개 seed 확보
  │
  ├─ [3] Intent-Aware Graph Expansion
  │   classify_intent(query) → read/write/delete
  │   dominant intent ≥ 0.6 → intent-specific relation weights 적용
  │   BFS(max_depth=2), relation_weight × distance_decay
  │   → write_file: 0.7 (COMPLEMENTARY of read_file)
  │
  ├─ [4] Embedding Cosine Score (optional)
  │   all-MiniLM-L6-v2, Ollama, OpenAI, vLLM 등
  │   → read_file: 0.78, write_file: 0.31, save_to_db: 0.72
  │
  ├─ [5] Annotation Score
  │   classify_intent(query) → QueryIntent
  │   compute_annotation_scores(intent, tools)
  │   → read_file: 0.85 (readOnly match), delete_file: 0.0 (mismatch)
  │
  ├─ [6] Adaptive wRRF Fusion
  │   corpus 크기별 동적 가중치:
  │     ≤30 tools:  kw=0.35, graph=0.30, emb=0.30, ann=0.05
  │     ≤100 tools: kw=0.30, graph=0.35, emb=0.25, ann=0.10
  │     >100 tools: kw=0.25, graph=0.40, emb=0.15, ann=0.20
  │   (embedding 미활성 시: kw=0.5, graph=0.5, ann=0.2)
  │
  ├─ [7] Post-Fusion Boosts
  │   ① Name overlap: exact match 2.0x, 2+ overlap 1.25+, 1 overlap 1.1x
  │   ② HTTP method-intent alignment: GET+read 1.1x, POST+write 1.15x, DELETE+delete 1.15x
  │   ③ Embedding rerank: top-10 후보 description 유사도 재평가 (1.2x max)
  │   ④ History penalty: 이전 호출 도구 0.8x
  │
  └─ [8] Post-Processing
      Cross-encoder reranking (optional)
      MMR diversity reranking (optional)
      → Top-K 반환 + inter-result relations enrichment
```

## RRF (Reciprocal Rank Fusion)

```python
def rrf_score(ranks: dict[str, list[int]], k: int = 60) -> dict[str, float]:
    """
    ranks: {tool_name: [rank_in_method_1, rank_in_method_2, ...]}
    """
    scores = {}
    for tool, tool_ranks in ranks.items():
        scores[tool] = sum(1.0 / (k + r) for r in tool_ranks)
    return scores
```

BEIR 벤치마크 근거:
- BM25 only: NDCG@10 = 43.4, Recall = 0.72
- Dense only: NDCG@10 = ~45
- **Hybrid + RRF: NDCG@10 > 52.6, Recall = 0.91**

## Workflow Coverage

고유 평가 지표:

> "파일을 읽고 수정해서 저장하라"
> → read_file, write_file **모두** retrieve 되어야 함

벡터만으로는 write_file을 놓칠 수 있지만,
COMPLEMENTARY 관계를 통해 graph expansion에서 자동 포함.

## 3-Tier 검색 아키텍처 (NEW)

상세: [design/search-modes.md](search-modes.md)

```
Tier 0: No-LLM (기본)     → BM25 + graph expansion, <50ms
Tier 1: Small-LLM (선택)  → + query expansion (1.5B~3B), +200ms
Tier 2: Full-LLM (선택)   → + intent decomposition (3B~7B+), +500ms~2s
```

두 가지 Mode:
- **Pre-Query Search**: AI 호출 전, 사용자 입력으로 tool 후보 검색
- **Model-Driven Search**: Agent LLM이 직접 tool graph 검색 API 호출

## Annotation-Aware Retrieval (Phase 2.5)

상세: [design/annotation-retrieval.md](annotation-retrieval.md)

| 구성 요소 | 역할 |
|-----------|------|
| Intent Classifier | query → read/write/delete intent (한/영 키워드) |
| Annotation Scorer | intent ↔ annotation alignment (0.0~1.0) |
| wRRF 4th source | annotation_scores, weight=0.2 (보조 signal) |
| OpenAPI 추론 | HTTP method → annotation 자동 매핑 |

## Intent-Aware Graph Weights (Phase 3)

query intent에 따라 그래프 관계 가중치를 동적 조정.
`ontology/schema.py`의 `INTENT_RELATION_WEIGHTS` 참조.

| 관계 | Default | read | write | delete |
|------|:---:|:---:|:---:|:---:|
| SIMILAR_TO | 0.8 | **1.0** | 0.5 | 0.4 |
| REQUIRES | 1.0 | 0.8 | **1.0** | 0.9 |
| COMPLEMENTARY | 0.7 | 0.4 | **0.95** | 0.3 |
| CONFLICTS_WITH | 0.2 | 0.2 | 0.3 | **0.5** |
| BELONGS_TO | 0.5 | 0.6 | 0.5 | 0.5 |
| PRECEDES | 0.9 | 0.5 | 0.7 | 0.8 |

예시:
- read 쿼리 "list pods": SIMILAR_TO 가중치 1.0 → 같은 리소스 GET/LIST 도구가 높은 순위
- write 쿼리 "create pod": COMPLEMENTARY 0.95 → PATCH/PUT 도구도 함께 상위 노출
- delete 쿼리 "remove user": CONFLICTS_WITH 0.5 → 충돌 경고 도구 인식

## 개선 이력

| 문제 | Phase 1 | Phase 2 | Phase 2.5 | Phase 3 |
|------|---------|---------|-----------|---------|
| token exact match | BM25 TF-IDF | - | - | stopword threshold 70% |
| embedding 미연결 | - | all-MiniLM-L6-v2 | - | seed top-5 확대 |
| 가중합 scoring | RRF fusion | wRRF + embedding | + annotation | adaptive wRRF (corpus별) |
| LLM 없이만 동작 | SearchMode enum | Tier 1/2 | - | - |
| 행동적 의미 무시 | - | - | intent↔annotation | intent-aware graph weights |
| 이름 매칭 약함 | - | - | - | exact match 2.0x boost |
| seed 부족 | BM25 top-10 | + embedding | - | + annotation match seeds |
