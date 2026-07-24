# 벤치마크

벤치마크는 graph retrieval이 tool selection 품질을 높이고 context 크기를 줄이는지
확인하기 위해 사용합니다.

## 측정 항목

- Recall@K
- MRR
- NDCG
- candidate count
- token/context reduction
- plan hit rate
- failure reason classification

## Suite

Repository의 `benchmarks/` 아래에 deterministic benchmark와 fixture suite가 있습니다.

개발 중에는 작은 suite를 사용하고, 긴 LLM-backed suite는 release candidate 또는 public
claim을 갱신할 때만 돌립니다.

```bash
python -m benchmarks.run_benchmark
python -m benchmarks.xgen_api_scale.run
```

과거 benchmark 노트와 raw result context는 repository의 `docs/benchmarks.md`를
참고하세요.

