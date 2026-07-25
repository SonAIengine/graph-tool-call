---
title: 품질 게이트
description: search, target selection, plan, execute 변경을 재현 가능한 기준으로 검증하는 방법입니다.
---

# 품질 게이트

품질 게이트는 search와 planning 개선을 감이 아니라 수치로 보게 해줍니다.

게이트는 “모든 가능한 API call이 성공한다”를 증명하기 위한 것이 아닙니다. release
가능 여부를 판단하고, 성공과 실패가 모두 진단 가능하게 남는지를 확인하기 위한 장치입니다.

## 개발 루프

구현 중에는 빠른 deterministic check를 먼저 사용합니다.

```bash
make quick
poetry run pytest tests/test_graphify_metadata.py tests/test_openapi_readiness.py -q
```

OpenAPI ingest, retrieval, selector, plan logic이 크게 바뀔 때만 더 큰 OpenAPI와
LLM 검증을 돌립니다.

## Gate Level

| Level | 목적 | 일반적인 명령 |
| --- | --- | --- |
| quick | local contract와 regression loop | `make quick` |
| docs | 문서 typecheck/build/search index | `cd website && npm run build` |
| collection | OpenAPI readiness와 search case | Quality Lab 또는 fixture replay |
| release | 전체 lint/test/build와 selected benchmark | `make release-check`와 benchmark gate |

## 권장 Metric

대형 OpenAPI collection에서는 다음을 봅니다.

- semantic action known rate
- primary resource assigned rate
- path/module assigned rate
- search Hit@K
- plan target hit rate
- execute read success rate
- structured failure classification rate
- uncaught server error count

목표는 모든 API call을 CI에서 성공시키는 것이 아닙니다. 모든 성공과 실패가 설명
가능하게 남는 것이 목표입니다.

## Acceptance Record

각 gate run은 compact record로 남깁니다.

```json
{
  "gate": "xgen-scale-semantic",
  "version": "0.32.1",
  "case_count": 50,
  "search_hit_at_8": 1.0,
  "plan_hit_rate": 0.86,
  "uncaught_server_errors": 0,
  "artifact": "/tmp/gtc-quality-gate.json"
}
```

## Failure Taxonomy

게이트 결과를 해석하기 전에 failure를 분류해야 합니다.

| Failure | 의미 |
| --- | --- |
| `not_retrieved` | expected tool이 candidate set에 없음 |
| `selector_mismatch` | 후보에는 있으나 최종 target이 틀림 |
| `unsatisfied_field` | plan이 required value를 채우지 못함 |
| `auth_context_required` | API 호출 전에 실행이 차단됨 |
| `auth_failed` | downstream API가 credential을 거부함 |
| `http_4xx` / `http_5xx` | downstream API 실패 |
| `uncaught_server_error` | adapter 또는 service bug |

## 비싼 Gate를 돌릴 때

model-in-the-loop 또는 live API gate는 다음 상황에서 실행합니다.

- retrieval/selector/plan logic이 바뀐 경우
- public README 또는 docs benchmark claim이 바뀐 경우
- release candidate를 자르는 경우
- production incident가 ranking 또는 planning 품질과 연결된 경우

일반적인 문구 수정이나 docs 변경에는 snapshot replay를 사용합니다.

## 관련 문서

- [Quality Lab](../validation/quality-lab.md)
- [Release Gates](../validation/release-gates.md)
- [BFCL 스타일 평가](../validation/bfcl-style-evaluation.md)
