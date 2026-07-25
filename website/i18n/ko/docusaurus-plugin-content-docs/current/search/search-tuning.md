---
title: 검색 튜닝
description: alias, semantic metadata, contract, validation gate로 retrieval 품질을 개선합니다.
---

# 검색 튜닝

Prompt를 바꾸기 전에 catalog evidence를 개선하는 순서로 search를 튜닝합니다.

Search tuning은 측정 가능해야 합니다. weight나 prompt를 바꾸기 전에 작은 query suite를
export하고 Top-K hit, selector decision, miss evidence를 기록합니다.

## 작업 순서

1. `semantic_summary`를 확인합니다.
2. contract coverage를 확인합니다.
3. `include_evidence=True`로 top miss를 점검합니다.
4. generic alias를 option으로 추가합니다.
5. deterministic evidence가 부족할 때만 manual edge를 추가합니다.
6. trace-learning suggestion은 검증 후 promote합니다.
7. search gate를 다시 실행합니다.

## Tuning Surface

| Surface | 언제 쓰나 | Evidence |
| --- | --- | --- |
| semantic metadata | action/resource/shape가 unknown | `semantic_summary` |
| IO contracts | producer 또는 required field가 빠짐 | `api_contract` coverage |
| aliases | 도메인 언어와 OpenAPI name이 다름 | paired query test |
| candidate expansion | producer 부족으로 plan 실패 | `unsatisfied_field` count |
| selector policy | 정답 tool은 Top-K에 있는데 final target이 틀림 | `target_selector.rank_signals` |
| learning suggestions | 반복 성공 trace가 안정적 | promoted suggestion record |

## Diagnostic Loop

```text
choose query suite
  -> run retrieval with evidence
  -> classify misses
  -> improve metadata/contract/aliases
  -> re-run same suite
  -> promote only repeatable improvements
```

Miss category:

| Category | 의미 | 가능한 조치 |
| --- | --- | --- |
| `not_retrieved` | expected target이 Top-K 밖 | semantic metadata 또는 alias |
| `low_rank` | expected target은 있지만 rank가 낮음 | score signal 또는 sibling control |
| `wrong_shape` | list/detail/count/mutation mismatch | result shape derivation |
| `producer_missing` | target은 찾았지만 field를 못 채움 | contract extraction |
| `selector_mismatch` | LLM이 약한 sibling을 선택 | target selector evidence |

## Weight Changes

Weight 변경은 마지막에 사용합니다. catalog 전체에 영향을 주고 나쁜 metadata를 숨길 수
있습니다. 먼저 local하고 설명 가능한 evidence를 개선합니다.

- 더 나은 `canonical_action`
- 더 나은 `primary_resource`
- 더 나은 `result_shape`
- 더 깔끔한 `path_module`
- generic alias
- promoted trace evidence

## 피해야 할 것

- engine에 product-specific operation name을 하드코딩
- raw description boost를 과하게 주어 noisy spec이 결과를 지배하게 만들기
- 단일 성공 실행을 영구 ranking truth로 취급
- query 하나를 고치려고 broad weight를 변경하기
- manual query 1개만 보고 개선을 선언하기

## Acceptance Gates

Tuning 변경은 최소 아래를 보고해야 합니다.

- query count
- Top-1 hit rate
- Top-3 또는 Top-8 hit rate
- average candidate count
- max candidate count
- selector override count
- uncaught error count

XGEN식 collection에서는 plan hit rate와 `unsatisfied_field` count도 함께 봅니다.
Search 품질은 planning이 target을 실제로 사용할 수 있을 때 의미가 있습니다.

## 관련 문서

- [Validation Benchmarks](../validation/benchmarks.md)
- [Learning Loop](../learning/shadow-promotion.md)
- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
