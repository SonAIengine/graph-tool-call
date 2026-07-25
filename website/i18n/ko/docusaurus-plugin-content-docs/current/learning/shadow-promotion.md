---
title: Shadow와 Promotion
description: observe, shadow, promote 단계로 trace learning을 안전하게 적용합니다.
---

# Shadow와 Promotion

기본 learning policy는 observe, shadow, promote입니다.

## Modes

| Mode | Behavior |
| --- | --- |
| Observe | scrubbed trace record만 저장 |
| Shadow | learning-applied ranking을 계산하지만 execution에는 반영하지 않음 |
| Promoted | 검증된 low-weight boost를 retrieval과 target selection에 적용 |

## Promotion Gate

Suggestion은 아래 조건을 만족할 때 promotable해집니다.

- 같은 query family가 반복 성공
- 같은 target 또는 plan path가 안정적
- 최근 failure rate가 허용 범위
- scrubbing에서 sensitive value가 발견되지 않음
- Quality Lab 또는 operator review 승인

## 관련 문서

- [Suggestions](./suggestions.md)
- [Search Tuning](../search/search-tuning.md)
