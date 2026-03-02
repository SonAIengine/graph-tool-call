# Retrieval Engine — 설계 문서

**WBS**: 1-7, 2-2, 2.5
**파일**: `retrieval/engine.py`, `retrieval/keyword.py`, `retrieval/embedding.py`, `retrieval/intent.py`, `retrieval/annotation_scorer.py`

## Hybrid 검색 파이프라인 (4-source wRRF)

```
Query: "사용자 파일을 읽고 DB에 저장해줘"
  │
  ├─ [1] BM25-style Keyword Score
  │   tokenize + TF-IDF weighting
  │   → read_file: 0.42, write_file: 0.15, query_db: 0.38
  │
  ├─ [2] Embedding Cosine Score (optional)
  │   all-MiniLM-L6-v2 (384d)
  │   → read_file: 0.78, write_file: 0.31, save_to_db: 0.72
  │
  ├─ [3] Graph Expansion Score
  │   Top-5 seeds from [1]+[2] → BFS(max_depth=2)
  │   relation weight × distance decay
  │   → write_file: 0.7 (COMPLEMENTARY of read_file)
  │
  ├─ [4] Annotation Score (NEW — Phase 2.5)
  │   classify_intent(query) → QueryIntent
  │   compute_annotation_scores(intent, tools) → alignment scores
  │   → read_file: 0.85 (readOnly match), delete_file: 0.0 (mismatch)
  │
  └─ [5] wRRF Score Fusion
      sources = [(BM25, 1.0), (Graph, 1.0), (Embedding, 1.0), (Annotation, 0.2)]
      final = Σ weight_i/(k + rank_i) for each source
      → Top-K 반환
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

## 개선 이력

| 문제 | Phase 1 개선 | Phase 2 개선 | Phase 2.5 개선 |
|------|-------------|-------------|---------------|
| token exact match | BM25-style TF-IDF | - | - |
| embedding 미연결 | - | all-MiniLM-L6-v2 | - |
| 가중합 scoring | RRF fusion | wRRF + embedding | + annotation source |
| tags TypeError | 버그 수정 | - | - |
| LLM 없이만 동작 | SearchMode enum | Tier 1/2 구현 | - |
| 행동적 의미 무시 | - | - | intent↔annotation alignment |
