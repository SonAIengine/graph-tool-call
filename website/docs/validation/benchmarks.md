# Benchmarks

Benchmarks are used to check whether graph retrieval improves tool selection
quality and reduces context size.

## What Is Measured

- Recall@K
- MRR
- NDCG
- candidate count
- token/context reduction
- plan hit rate
- failure reason classification

## Suites

The repository includes deterministic benchmark and fixture suites under
`benchmarks/`.

Use small suites during development and reserve long LLM-backed suites for
release candidates or public claim updates.

```bash
python -m benchmarks.run_benchmark
python -m benchmarks.xgen_api_scale.run
```

See the repository `docs/benchmarks.md` for the historical benchmark notes and
raw result context.

