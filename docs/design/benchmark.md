# Benchmark — 설계 문서

**파일**: `benchmarks/metrics.py`, `benchmarks/reporter.py`, `benchmarks/run_benchmark.py`, `benchmarks/pipeline.py`

## 실행 모드

| 모드 | 명령 | 측정 대상 | LLM 필요 |
|------|------|---------|:---:|
| `retrieval` | `python -m benchmarks.run_benchmark` | top-K 검색 품질 | ✗ |
| `e2e` | `--mode e2e -m qwen3:4b` | baseline vs retrieve 비교 | ✓ |
| `pipeline` | `--mode pipeline` | 다중 파이프라인 비교 | ✓ |

## 데이터셋 (8개)

| 이름 | 도구 수 | 쿼리 수 | 타입 | 특징 |
|------|:---:|:---:|------|------|
| petstore | 19 | 20 | OpenAPI | 전통 REST CRUD |
| github | 50 | 40 | OpenAPI | 대규모 계층적 API |
| mixed_mcp | 38 | 30 | MCP×2 | filesystem + github |
| k8s | 248 | 50 | OpenAPI | 대규모, K8s core/v1 |
| playwright | 22 | 25 | MCP | 브라우저 자동화 |
| ecommerce | 46 | 43 | OpenAPI | E-Commerce, 한글 쿼리 포함 |
| multi_mcp | 60 | 30 | MCP×3 | playwright + filesystem + github |
| cli_agent | 78 | 50 | MCP×5 | shell + git + docker + github + filesystem |

## 메트릭

### 검색 품질 (Retrieval)

| 메트릭 | 설명 | 파일 |
|--------|------|------|
| **Recall@K** | top-K에서 관련 도구 발견 비율 | `metrics.py` |
| **MRR** | 첫 관련 결과의 역순위 평균 | `metrics.py` |
| **MAP** | 각 관련 hit에서 precision 평균 | `metrics.py` |
| **NDCG@K** | 순위 가중 정규화 이득 | `metrics.py` |
| **Precision@K** | top-K 중 관련 비율 | `metrics.py` |
| **HitRate@K** | 적어도 1개 관련 도구 존재 비율 | `metrics.py` |
| **MissRate** | Recall=0 쿼리 비율 (완전 실패) | `metrics.py` |
| **Workflow Coverage** | 워크플로우 단계 커버율 | `metrics.py` |

### 통계 (Statistical)

| 메트릭 | 설명 | 용도 |
|--------|------|------|
| **95% CI** | Bootstrap 신뢰구간 (1000회) | 결과 변동성 파악 |
| **Stdev** | 표본 표준편차 | 메트릭 분산 |
| **Paired t-test** | baseline vs retrieve 유의성 | p < 0.05 여부 |

### 효율성 (Efficiency)

| 메트릭 | 설명 |
|--------|------|
| **Token Efficiency** | accuracy / (avg_tokens / 1000) — 토큰당 정확도 |
| **Token Reduction** | baseline 대비 토큰 절감율 |
| **Recall@K 곡선** | K=3, 5, 10에서 recall 변화 |

### Component Attribution

top-1 결과의 각 scoring source 기여도:

```
keyword: 8.28    # BM25 점수
graph:   1.00    # 그래프 확장 점수
embedding: 0.00  # embedding 유사도 (비활성 시 0)
annotation: 0.67 # intent-annotation 정렬 점수
```

## 콘솔 출력 예시

```
  GitHub REST API Subset  (50 tools, 40 queries)
  ──────────────────────────────────────────────────
  Recall@5             90.0%  (95% CI: 80.0%–97.5%)
  MRR                  0.743  (95% CI: 0.623–0.854)
  MAP                  0.743
  NDCG@5               0.782
  Recall Curve         @3=85.0%, @5=90.0%, @10=90.0%
  HitRate@5            90.0%
  MissRate             10.0%  (4 queries)
  Avg Latency          1.2ms
```

## Baseline 관리

```bash
# baseline 저장
python -m benchmarks.run_benchmark --mode pipeline --save-baseline

# baseline 대비 비교
python -m benchmarks.run_benchmark --mode pipeline --diff

# 실패 쿼리 분석
python -m benchmarks.run_benchmark --mode pipeline --failures
```

baseline은 `benchmarks/results/baseline.json`에 저장.
`--diff`로 실행하면 각 메트릭의 개선/하락을 표시.

## 벤치마크 결과 (v0.12 기준)

### Retrieval-Only (BM25 + Graph, embedding 미사용, top_k=5)

| Dataset | Tools | Recall@5 | MRR | MAP | HitRate | MissRate |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| Petstore | 19 | 98.3% | 0.917 | 0.879 | 100% | 0% |
| GitHub | 50 | 90.0% | 0.743 | 0.743 | 90.0% | 10.0% |
| Mixed MCP | 38 | 93.3% | 0.894 | 0.894 | 93.3% | 6.7% |
| K8s | 248 | 93.0% | 0.742 | 0.738 | 94.0% | 6.0% |
| Playwright | 22 | 90.7% | 0.900 | 0.887 | 92.0% | 8.0% |
| E-Commerce | 46 | 89.5% | 0.766 | 0.752 | 90.7% | 9.3% |
| Multi-MCP | 60 | 91.1% | 0.858 | 0.831 | 93.3% | 6.7% |
| CLI Agent | 78 | 92.5% | 0.786 | 0.774 | 94.0% | 6.0% |

### E2E (qwen3.5:4b, baseline vs retrieve-k5)

| Dataset | Tools | baseline Acc | retrieve Acc | Token 절감 |
|---------|:---:|:---:|:---:|:---:|
| K8s | 248 | 4.0% | **78.0%** | 76% |
| CLI Agent | 78 | 36.0% | **48.0%** | 91% |
| Multi-MCP | 60 | 33.3% | **40.0%** | 89% |
| GitHub | 50 | 22.5% | 20.0% | 87% |

핵심: 도구 수 > 50일 때 retrieve 파이프라인의 accuracy 이득이 극적.

## 확장 포인트

### 향후 추가 가능한 메트릭

- **Graded Relevance**: ground truth에 required/optional/contextual 등급 → NDCG 의미 강화
- **Error Taxonomy**: 실패 쿼리 자동 분류 (name mismatch, intent mismatch, OOD)
- **Alpha-nDCG**: 다양성 고려 순위 메트릭
- **Rank Correlation (Kendall tau)**: 파이프라인 간 순위 일관성

### Ground Truth 개선 방향

```json
{
  "query": "Update pet",
  "tools": {
    "required": ["updatePet"],
    "optional": ["updatePetWithForm"],
    "contextual": ["getPetById"]
  }
}
```

현재는 flat `expected_tools` 리스트만 지원. 다중 등급 지원 시 NDCG 정확도 향상.
