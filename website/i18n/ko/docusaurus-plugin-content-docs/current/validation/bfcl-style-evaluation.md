---
title: BFCL 스타일 평가
description: tool-call benchmark 방법론으로 graph-tool-call을 검증하는 방식을 설명합니다.
---

# BFCL 스타일 평가

BFCL-style evaluation은 tool-call 품질에 대한 public claim을 만들 때 사용합니다.
빠른 개발 loop보다 무겁기 때문에 release candidate나 benchmark claim 업데이트
시점에 실행하는 것이 맞습니다.

이 문서는 영구 leaderboard claim이 아니라 평가 방법론을 설명합니다. 결과는 dataset,
model, retrieval mode, Top-K 정책, run artifact가 함께 명시될 때만 의미가 있습니다.

## 평가 Layer

| Layer | 목적 | 실행 빈도 |
| --- | --- | --- |
| deterministic retrieval | expected tool이 후보에 올라오는지 확인 | search 변경마다 |
| model-in-the-loop target selection | 줄어든 catalog에서 LLM이 올바른 target을 고르는지 확인 | release candidate |
| argument readiness | 선택된 call에 argument evidence가 충분한지 확인 | release candidate |
| execution-safe subset | 안전한 경우 fixture 또는 실제 API 실행 확인 | gated/manual |

full BFCL-style run을 일반 inner loop로 쓰지 않습니다. 개발 중에는 작은 deterministic
fixture로 빠르게 회귀를 잡고, public claim을 갱신할 때만 큰 검증을 돌립니다.

## 무엇을 측정하나

- target selection correctness
- plan validity
- argument readiness
- 안전한 경우 execution outcome
- failure classification
- latency와 token context budget

## 필수 Run Metadata

저장되는 결과에는 최소한 다음을 포함해야 합니다.

- 날짜
- graph-tool-call version 또는 commit
- dataset과 case count
- model/provider
- retrieval mode와 Top-K
- prompt mode 또는 native tool-call mode
- argument 판정 방식
- output artifact path
- 알려진 limitation

## 예시 Workflow

```bash
make quick

poetry run python -m benchmarks.bfcl_tool_selection.run \
  --limit 25 \
  --top-k 5 \
  --json > /tmp/gtc-bfcl-smoke.json
```

smoke run은 regression을 빠르게 찾기 위한 용도입니다. 더 큰 model-in-the-loop run은
공식 문서, README, release note의 benchmark claim을 갱신할 때 사용합니다.

## 피해야 할 것

좁은 smoke test 결과를 benchmark number처럼 공개하지 않습니다. public claim은
dataset, model, run configuration, stored result artifact와 연결되어야 합니다.

특히 다음을 피합니다.

- deterministic retrieval score와 LLM tool-call score를 섞어서 보고
- dataset/evaluator가 다른 benchmark와 직접 비교
- 실패 case 숨기기
- 반복 없이 한 번 성공한 run만 보고
- dev host 실행 결과를 일반 model 품질 claim으로 확대

## Reporting Template

```text
Dataset:
Model:
graph-tool-call version:
Retrieval mode:
Top-K:
Case count:
Metric:
Result:
Artifact:
Limitations:
```

## 관련 문서

- [Benchmarks](./benchmarks.md)
- [Release Gates](./release-gates.md)
- [XGEN Scale Gates](./xgen-scale-gates.md)
