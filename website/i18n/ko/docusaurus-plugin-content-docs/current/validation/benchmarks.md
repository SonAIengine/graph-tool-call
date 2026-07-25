---
title: Benchmark
description: retrieval, selection, planning, context reduction 품질을 측정합니다.
---

# Benchmark

Benchmark는 변경이 tool discovery와 실행 품질을 실제로 좋게 만들었는지
확인하기 위한 장치입니다. 매번 긴 LLM 검증을 돌리는 대신, deterministic
suite는 자주 돌리고 LLM-backed run은 release candidate나 public claim 갱신
시에만 돌리는 것이 좋습니다.

## 측정 지표

| Metric | Stage | 의미 |
| --- | --- | --- |
| `hit@k` | retrieval | expected target이 Top-K 안에 있는지 |
| `top1` | retrieval | expected target이 1위인지 |
| `mrr` | retrieval | expected target rank 품질 |
| `ndcg` | retrieval | 여러 relevant target이 있을 때 rank 품질 |
| `candidate_count` | retrieval | downstream으로 넘긴 tool 수 |
| `context_reduction` | retrieval | LLM context에서 줄인 schema/text 비율 |
| `selector_accuracy` | target selection | final selected target 정확도 |
| `plan_hit_rate` | plan | expected target/path로 plan이 합성됐는지 |
| `execute_success_rate` | execute | 안전한 실행 case가 성공했는지 |
| `failure_reason_coverage` | execute | 실패가 안정 reason code로 분류됐는지 |
| `latency_ms` | all | stage별 시간 |

## 개발 루프

retrieval, graphify, plan, learning code를 수정할 때는 먼저 작은 suite를
돌립니다.

```bash
make quick
```

문서 사이트만 수정했다면 website build가 적절합니다.

```bash
cd website
npm run typecheck
npm run build
```

## Deterministic benchmark

```bash
python -m benchmarks.run_benchmark
```

PR, README, docs에서 숫자를 언급할 때는 result JSON을 저장하세요.

```bash
python -m benchmarks.run_benchmark \
  --output benchmarks/results/my_run.json
```

## XGEN-scale snapshot

대형 OpenAPI catalog regression은 live API나 full LLM run 없이 snapshot replay로
먼저 봅니다.

```bash
make xgen-scale-snapshot
```

주요 gate:

- semantic action/resource/module coverage
- search hit@8와 Top-1
- target selector accuracy
- average/max candidate count
- schema context reduction
- uncaught error count

## LLM-backed evaluation

LLM 검증 결과에는 반드시 다음을 남깁니다.

| Field | 이유 |
| --- | --- |
| model/provider | 결과가 모델에 의존함 |
| prompt/template version | target selection이 prompt에 민감함 |
| dataset version | 다른 dataset 비교 방지 |
| graph-tool-call version | library behavior와 연결 |
| run config | 재현성 |
| raw result artifact | 추후 분석 가능 |

commit된 fixture나 저장 artifact 없이 public quality claim을 업데이트하지
마세요.

## 관련 문서

- [Quality Lab](./quality-lab.md)
- [XGEN Scale Gate](./xgen-scale-gates.md)
- [BFCL 스타일 평가](./bfcl-style-evaluation.md)
- [Release Gate](./release-gates.md)
