---
title: 검색 튜닝
description: alias, semantic metadata, contract, validation gate로 retrieval 품질을 개선합니다.
---

# 검색 튜닝

Prompt를 바꾸기 전에 catalog evidence를 개선하는 순서로 search를 튜닝합니다.

## 작업 순서

1. `semantic_summary`를 확인합니다.
2. contract coverage를 확인합니다.
3. `include_evidence=True`로 top miss를 점검합니다.
4. generic alias를 option으로 추가합니다.
5. deterministic evidence가 부족할 때만 manual edge를 추가합니다.
6. trace-learning suggestion은 검증 후 promote합니다.
7. search gate를 다시 실행합니다.

## 피해야 할 것

- engine에 product-specific operation name을 하드코딩
- raw description boost를 과하게 주어 noisy spec이 결과를 지배하게 만들기
- 단일 성공 실행을 영구 ranking truth로 취급

## 관련 문서

- [Validation Benchmarks](../validation/benchmarks.md)
- [Learning Loop](../learning/shadow-promotion.md)
