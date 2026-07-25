---
title: Shadow와 Promotion
description: observe, shadow, promote 단계로 trace learning을 안전하게 적용합니다.
---

# Shadow와 Promotion

기본 learning policy는 다음입니다.

```text
observe -> shadow -> promote
```

성공 trace 1개는 evidence일 뿐 즉시 production rule이 아닙니다. 이 정책은 단일
성공 run에 overfit되는 것을 막습니다.

## Modes

| Mode | Behavior | Ranking Impact |
| --- | --- | --- |
| Observe | scrubbed attempt와 suggestion 저장 | 없음 |
| Shadow | learning-applied ranking을 현재 ranking 옆에서 계산 | 실제 실행에는 영향 없음 |
| Promoted | 검증된 low-weight signal 적용 | 작은 additive boost |

## Observe

Observe mode에서는 adapter가 compact attempt와 suggestion을 저장합니다.

```python
record = build_trace_learning_record(...)
suggestions = derive_learning_suggestions(record, history=attempts)
```

collection에 learning을 처음 켤 때는 observe mode부터 시작합니다.

## Shadow

Shadow mode는 learning이 활성화되었다면 어떤 결과가 나왔을지 계산하지만, 실제 selected
target이나 실행 plan은 바꾸지 않습니다.

추적할 항목:

- 현재 selected target
- shadow selected target
- 현재 rank
- shadow rank
- expected target의 rank가 개선됐는지
- 실패를 피할 수 있었는지

dev와 초기 production rollout에서는 shadow mode가 기본값으로 적합합니다.

## Promote

Retrieval과 target selection에 영향을 주는 것은 `promoted` suggestion뿐입니다.

Promotion은 아래 중 하나 이상을 요구해야 합니다.

- 같은 query family의 반복 성공
- Quality Lab 검증
- operator 승인
- low-risk collection에 대한 통제된 rollout rule

## Promotion Gate

Suggestion은 아래 조건을 만족할 때만 promotable해야 합니다.

- 같은 query family가 반복 성공
- 같은 target 또는 plan path가 안정적
- 최근 failure rate가 허용 범위
- scrubbing에서 sensitive value가 발견되지 않음
- Quality Lab 또는 operator review 승인

## Failure Handling

Learning은 실패도 보존해야 합니다. 실패 attempt는 promotion을 막거나 plan path의
위험성을 설명하고, product UI가 문제가 search, target selection, plan synthesis,
auth, HTTP, cleanup, assertion 중 어디였는지 보여주게 합니다.

## 관련 문서

- [Suggestions](./suggestions.md)
- [Scrubbing](./scrubbing.md)
- [Search Tuning](../search/search-tuning.md)
