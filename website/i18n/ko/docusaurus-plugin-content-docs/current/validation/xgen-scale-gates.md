---
title: XGEN Scale Gate
description: 대형 API collection snapshot으로 enterprise catalog 품질을 보호합니다.
---

# XGEN Scale Gate

XGEN scale gate는 실제 또는 replay된 대형 API collection snapshot으로
graph-tool-call이 enterprise catalog 규모에서도 잘 동작하는지 검증합니다.
BO dev data는 regression dataset이지, product-specific hard-coding 대상이
아닙니다.

## 왜 필요한가

작은 OpenAPI 예제에서는 다음 문제가 잘 드러나지 않습니다.

- 수백, 수천 개의 비슷한 operation id
- 한국어 summary와 영어 tool name 혼합
- 반복되는 request wrapper와 response envelope
- generic paging/search/context field
- list/detail/count/update sibling API
- 모든 edge를 그리면 읽을 수 없는 대형 graph

scale gate는 이런 조건에서 generic engine logic이 유지되는지 봅니다.

## 핵심 metric

| Metric | 목표 방향 |
| --- | --- |
| `canonical_action_known_rate` | 높을수록 좋음 |
| `primary_resource_assigned_rate` | 높을수록 좋음 |
| `path_module_assigned_rate` | 높을수록 좋음 |
| `search_hit_at_8` | 높을수록 좋음 |
| `search_top_1` | 높을수록 좋음 |
| `selector_exact_rate` | 높을수록 좋음 |
| `avg_candidate_count` | LLM context에 맞게 낮게 |
| `max_candidate_count` | bounded |
| `avg_schema_context_reduction` | 높을수록 좋음 |
| `uncaught_server_error_count` | 0 |

threshold는 fixture나 Quality Lab suite와 함께 관리합니다. library에는 generic
signal과 deterministic behavior만 둡니다.

## 언제 돌리나

| 변경 유형 | 권장 gate |
| --- | --- |
| docs-only | website build |
| runner/event 수정 | focused runner test |
| retrieval scoring 수정 | saved snapshot replay |
| semantic build 수정 | snapshot replay와 semantic summary gate |
| OpenAPI contract extraction 수정 | snapshot replay와 contract coverage gate |
| plan synthesis 수정 | Plan Quality Lab case |
| public benchmark 갱신 | full deterministic + LLM-backed run |

## Snapshot workflow

```bash
make xgen-scale-snapshot
```

before/after 비교가 필요하면 output을 저장합니다.

```bash
make xgen-scale-snapshot \
  XGEN_SCALE_OUTPUT=benchmarks/results/xgen_scale_$(date +%Y%m%d).json
```

snapshot에는 collection identity, source hash, library version, build option,
metric summary가 남아야 합니다.

## Failure triage

| Failure | 가능 원인 |
| --- | --- |
| action known rate 하락 | semantic derivation 또는 operationId parsing 변경 |
| resource assignment 하락 | path/tag/resource alias 처리 변경 |
| candidate count 증가 | graph expansion 또는 BM25 field weighting 과다 |
| hit@8은 통과, selector exact 하락 | selector margin 또는 shape signal regression |
| plan hit 하락 | contract consumes/produces 또는 user input slot regression |
| live execute만 실패 | auth readiness, downstream API, adapter executor 문제 |

## 관련 문서

- [Benchmark](./benchmarks.md)
- [Quality Lab](./quality-lab.md)
- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Target 선택](../search/target-selection.md)
