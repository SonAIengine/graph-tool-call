# Retrieval Engine — 설계 문서

**WBS**: 1-7, 2-2
**파일**: `retrieval/engine.py`, `retrieval/keyword.py`, `retrieval/embedding.py`

## Hybrid 검색 파이프라인

```
Query: "사용자 파일을 읽고 DB에 저장해줘"
  │
  ├─ [1] BM25-style Keyword Score
  │   tokenize + TF-IDF weighting
  │   → read_file: 0.42, write_file: 0.15, query_db: 0.38
  │
  ├─ [2] Embedding Cosine Score (optional, Phase 2)
  │   all-MiniLM-L6-v2 (384d)
  │   → read_file: 0.78, write_file: 0.31, save_to_db: 0.72
  │
  ├─ [3] Graph Expansion Score
  │   Top-5 seeds from [1]+[2] → BFS(max_depth=2)
  │   relation weight × distance decay
  │   → write_file: 0.7 (COMPLEMENTARY of read_file)
  │
  └─ [4] RRF Score Fusion
      final = Σ 1/(k + rank_i) for each method
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

## 현재 문제점 → 개선

| 문제 | Phase 1 개선 | Phase 2 개선 |
|------|-------------|-------------|
| token exact match | BM25-style TF-IDF | - |
| embedding 미연결 | - | all-MiniLM-L6-v2 |
| 가중합 scoring | RRF fusion | RRF + embedding |
| tags TypeError | 버그 수정 | - |
