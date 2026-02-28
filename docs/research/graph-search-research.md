# Graph Search & LLM-Assisted Retrieval 리서치

## 동기

tool graph에서 검색할 때:
1. LLM 없이도 검색이 되어야 함 (기본)
2. LLM 붙이면 더 좋아져야 함 (enhanced)
3. 아주 작은 모델(1.5B)로도 검색 품질 향상이 가능해야 함

## 핵심 발견

### 1. AutoTool — Tool Transition Graph (2024)

**방법**: 에이전트의 과거 tool 사용 이력에서 "transition graph" 구축.
tool A 다음에 tool B를 자주 사용하면 A→B 엣지 강화.

```
historical trajectory:
  search → click → scroll → click → purchase
  search → filter → click → add_to_cart

transition graph:
  search → click (weight: 0.6)
  search → filter (weight: 0.3)
  click → scroll (weight: 0.4)
  click → purchase (weight: 0.3)
```

**결과**: LLM 비용 30% 절감, tool selection 정확도 유지.

**우리 적용**: PRECEDES 관계의 가중치를 사용 빈도로 보강할 수 있음 (Phase 4).

### 2. Agent-as-a-Graph — KG + Vector + wRRF (2024)

**방법**: Knowledge Graph 구조와 벡터 검색을 결합.
Weighted Reciprocal Rank Fusion (wRRF)으로 score 합산.

```
검색 파이프라인:
  1. Keyword search (BM25)        → rank_keyword
  2. Vector search (embedding)    → rank_vector
  3. Graph traversal (BFS/DFS)    → rank_graph

  wRRF(tool) = w₁/(k+rank_keyword) + w₂/(k+rank_vector) + w₃/(k+rank_graph)

  w₁, w₂, w₃ = query 특성에 따라 적응적 조정
```

**결과**: Recall@5 14.9% 개선 (vs 벡터만).

**우리 적용**: 현재 RRF를 이미 계획 중. wRRF로 가중치 적응 가능.

### 3. Tiered Architecture 리서치

LLM 크기별 가능한 task:

| Task | 필요 능력 | 최소 모델 | 지연 (로컬 GPU) |
|------|----------|----------|----------------|
| Keyword extraction | 토큰 분리 | 1.5B (Qwen2.5-1.5B) | ~50ms |
| Query expansion (동의어) | 어휘 지식 | 3B (Phi-3-mini) | ~100ms |
| 다국어 번역 | 다국어 | 3B+ | ~150ms |
| Intent decomposition | 문맥 이해 | 3-7B (Qwen2.5-3B) | ~200ms |
| JSON structured output | 포맷 준수 | 3B+ | ~150ms |
| Semantic reranking | 의미 비교 | 7B+ (Qwen2.5-7B) | ~300ms |
| Complex reasoning | 추론 | 14B+ | ~500ms+ |

### 4. Pre-Query vs Model-Driven

| | Pre-Query | Model-Driven |
|--|-----------|-------------|
| **시점** | AI 호출 전 | AI가 직접 |
| **주체** | 시스템 / 프레임워크 | Agent LLM |
| **장점** | 빠름, 결정론적 | 유연, 반복 가능 |
| **단점** | 쿼리 한번만 | LLM 호출 추가 |
| **사용 케이스** | bigtool 패턴 | 복잡한 워크플로우 |

### 5. Embedding 모델 비교

| 모델 | 크기 | 차원 | 한국어 | 라이선스 |
|------|------|------|-------|---------|
| all-MiniLM-L6-v2 | 22.7M | 384 | 제한적 | Apache 2.0 |
| multilingual-e5-small | 118M | 384 | ★★★ | MIT |
| bge-m3 | 568M | 1024 | ★★★ | MIT |
| nomic-embed-text | 137M | 768 | ★★☆ | Apache 2.0 |

**결론**: 다국어 지원 위해 `multilingual-e5-small` 또는 `bge-m3` 고려.
기본은 `all-MiniLM-L6-v2` (가장 가볍고 영어 최적화).

## 관련 연구

### ToolLLM (2023)

Sentence-BERT를 tool retrieval에 fine-tune.
16,000+ API에서 Recall@5 ~85% 달성.
→ 우리는 fine-tune 없이 일반 embedding + graph로 유사 성능 목표.

### RAG-MCP (2025)

벡터 유사도 기반 tool retrieval.
→ 우리와 같은 문제를 풀지만 graph 관계 없음.

### LAPIS (2025)

Tool description을 85% 압축하여 토큰 절약.
→ 우리의 검색 결과에 LAPIS 포맷 적용 가능 (Phase 4).

## 설계 반영

1. **3-Tier 아키텍처**: No-LLM → Small-LLM → Full-LLM
2. **SearchMode enum**: BASIC / ENHANCED / FULL
3. **SearchLLM 추상화**: Ollama / vLLM / OpenAI compatible
4. **Model-Driven API**: LLM이 직접 호출하는 search_tools, get_workflow
5. **wRRF**: 가중치 적응 RRF (query 특성 기반)
6. **다국어 embedding**: multilingual 모델 옵션

## 참고

- AutoTool (2024) — Tool transition graph
- Agent-as-a-Graph (2024) — KG + vector + wRRF
- ToolLLM (arXiv:2307.16789) — Sentence-BERT for API retrieval
- RAG-MCP (arXiv:2505.03275) — Vector-based tool retrieval
- LAPIS (arXiv:2602.18541) — 85% token reduction
