---
title: Shadow와 Promotion
description: observe, shadow, promote 단계로 trace learning을 안전하게 적용합니다.
---

# Shadow와 Promotion

기본 learning policy는 다음입니다.

```text
observe -> shadow -> promote
```

성공 trace는 evidence일 뿐 즉시 production rule이 아닙니다. Shadow와 promotion은 단일
성공 run, stale auth context, 일회성 API 상태에 시스템이 overfit되는 것을 막습니다.

## Modes

| Mode | 동작 | Ranking 영향 | 추천 사용처 |
| --- | --- | --- | --- |
| `observe` | scrub된 attempt와 suggestion 저장 | 없음 | collection에 처음 learning을 켤 때 |
| `shadow` | learning-applied ranking을 현재 ranking 옆에서 계산 | 실제 실행에는 영향 없음 | dev와 초기 production rollout |
| `promoted` | 검증된 low-weight signal 적용 | 작은 additive boost | 검증된 collection |

mode는 global, collection-level, Quality Lab-specific으로 둘 수 있습니다. evidence가
collection을 넘어서면 안 되므로 collection-level이 가장 안전한 기본값입니다.

## Observe Mode

Observe mode는 attempt와 suggestion을 기록합니다. 실제 behavior는 바꾸지 않습니다.

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
    merge_learning_suggestions,
)

record = build_trace_learning_record(
    query=query,
    collection_id=collection_id,
    selected_target=selected_target,
    plan_tools=plan_tools,
    success=success,
    failure_reason=failure_reason,
)

new_suggestions = derive_learning_suggestions(record, history=attempts)
suggestions = merge_learning_suggestions(
    existing=suggestions,
    incoming=new_suggestions,
    history=[*attempts, record],
)
```

Record가 scrub되고 suggestion이 collection-scoped라는 것을 증명할 때까지 observe mode를
사용하세요.

## Shadow Mode

Shadow mode는 learning이 활성화되었다면 어떤 결과가 나왔을지 계산하지만, 실제 selected
target과 실행 plan은 바꾸지 않습니다.

```python
from graph_tool_call.learning import apply_learning_suggestions

shadow = apply_learning_suggestions(
    query=query,
    candidates=current_candidates,
    suggestions=collection_suggestions,
    mode="shadow",
)
```

현재 결과와 shadow 결과를 모두 저장합니다.

| Field | 의미 |
| --- | --- |
| `current_selected_target` | live path가 사용한 target |
| `shadow_selected_target` | learning이 선호했을 target |
| `current_rank` | learning 전 expected target rank |
| `shadow_rank` | learning 적용 시 expected target rank |
| `rank_delta` | learning이 expected target을 위로 올렸는지 |
| `selected_target_changed` | learning이 execution behavior를 바꿨을지 |
| `failure_reason_changed` | learning이 알려진 failure를 피했을지 |

Auth readiness 때문에 execute가 불가능한 상황에서도 shadow mode는 유용합니다. Search와
target selection은 안전하게 비교할 수 있습니다.

## Promotion Gate

Suggestion은 evidence가 반복되고 깨끗할 때만 `promotable`이 되어야 합니다.

| Gate | Requirement |
| --- | --- |
| repeated success | 기본적으로 같은 query family가 최소 두 번 성공 |
| stable target | selected target 또는 plan path가 일관됨 |
| acceptable failure ratio | 최근 matching failure가 policy 이하 |
| scrubbed evidence | raw credential, raw body, 개인정보 없음 |
| collection isolation | suggestion이 같은 collection에 속함 |
| validation | Quality Lab, operator review, rollout policy 승인 |

기본 helper policy는 다음을 사용합니다.

```json
{
  "min_success_observations": 2,
  "max_recent_failure_ratio": 0.5,
  "max_attempts": 50,
  "max_suggestions": 100
}
```

Adapter는 더 엄격해도 됩니다. Write-capable collection은 `promoted` 전에 명시적 operator
approval을 요구하세요.

## Promotion Flow

```text
suggested
  -> promotable
  -> operator or policy approves
  -> promoted
  -> retrieval/selector sees low-weight signal
```

Promotion은 suggestion status와 metadata만 바꾸는 것이 좋습니다. 원본 attempt record를
rewrite하지 않습니다.

Promoted suggestion 예시:

```json
{
  "id": "target_preference:3f9d6dd00a0e50c1",
  "type": "target_preference",
  "target": "getRefundableOrders",
  "status": "promoted",
  "observations": 3,
  "promoted_by": "quality_lab",
  "promoted_at": "2026-07-25T08:00:00Z",
  "promotion_reason": "top1 improved in 3 repeated cases"
}
```

## Rejection Flow

Rejected suggestion도 보이게 남겨야 합니다. 왜 그럴듯한 pattern을 적용하지 않았는지
설명하는 근거가 됩니다.

| Rejection Reason | 의미 |
| --- | --- |
| `sensitive_evidence` | scrubbing이 unsafe data를 발견 |
| `unstable_target` | 반복 run에서 target이 달라짐 |
| `weak_shadow_delta` | shadow ranking 개선이 부족 |
| `operator_rejected` | 사람이 suggestion을 거절 |
| `collection_policy_blocked` | collection이 learning promotion을 허용하지 않음 |

Rejected suggestion은 promoted-mode ranking에 전달하지 않습니다.

## Ranking Impact

Learning signal은 작고 설명 가능해야 합니다.

| Signal | 의도한 효과 |
| --- | --- |
| `target_preference` | 같은 query family에서 가까운 target을 약간 올림 |
| `plan_path` | planner 선택이 동률일 때 과거 성공 path 선호 |
| `data_flow_edge` | 검증된 producer/consumer edge를 planning에 노출 |

Learning이 exact action/resource/contract evidence를 뒤집게 두지 마세요. Learning signal이
강한 deterministic signal을 뒤집으려 한다면 shadow 상태로 두고 review를 요구합니다.

## Rollout Strategy

1. 한 collection에서 `observe`로 시작합니다.
2. record가 scrub되고 bounded인지 확인합니다.
3. Quality Lab에서 `shadow`를 켭니다.
4. rank delta와 target change를 추적합니다.
5. 반복 성공이 있는 suggestion만 promote합니다.
6. low-risk read flow에만 `promoted` mode를 켭니다.
7. write flow는 cleanup assertion과 operator review가 있을 때만 추가합니다.

## Quality Lab Assertions

Quality Lab은 learning을 base search quality와 분리해서 검증해야 합니다.

```json
{
  "learning": {
    "mode": "shadow",
    "expected_target": "getRefundableOrders",
    "assertions": {
      "shadow_rank_lte_current_rank": true,
      "selected_target_changed": false,
      "raw_secret_present": false,
      "promotion_status": ["suggested", "promotable"]
    }
  }
}
```

이렇게 하면 learning evidence는 보이지만 production ranking이 바뀌었다고 과장하지 않게
됩니다.

## UI Checklist

| UI Element | 목적 |
| --- | --- |
| mode badge | observe, shadow, promoted 구분 |
| suggestion status | ranking 영향 여부 표시 |
| current vs shadow rank | 측정된 개선 표시 |
| evidence preview | scrubbed evidence 노출 |
| promote/reject controls | risky change에 operator governance 제공 |
| rejection reason | 나쁜 suggestion 반복 검토 방지 |
| collection scope | evidence가 collection을 넘지 않음을 표시 |

## Failure Handling

실패도 learning state의 일부로 남아야 합니다.

- 반복 failure는 promotion을 막아야 합니다.
- auth readiness failure만으로 target preference를 학습하면 안 됩니다.
- HTTP failure는 planning evidence 도출 전에 분류해야 합니다.
- cleanup failure는 write-case promotion을 막아야 합니다.
- uncaught server error는 learning evidence가 되면 안 됩니다.

Failure에서 배우는 것은 유용하지만, failure record는 future ranking을 boost하기보다
promotion을 제한하는 역할을 해야 합니다.

## Troubleshooting

| 증상 | 확인할 것 | 보완 |
| --- | --- | --- |
| 성공 1회가 곧바로 ranking을 바꿈 | active mode와 suggestion status | 새 suggestion은 observe/shadow 유지 |
| shadow target이 너무 자주 바뀜 | `ambiguous_target`, rank margin | operator review 요구 |
| promoted suggestion이 적용되지 않음 | query fingerprint와 collection id | 같은 query family와 같은 collection인지 확인 |
| write case가 promoted됨 | mutation safety와 cleanup assertion | cleanup 통과 전 promotion 차단 |
| operator가 promotion 이유를 알 수 없음 | promotion metadata | `promoted_by`, `promoted_at`, reason 저장 |

## 검증

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/ -q -k "learning or quality_lab"
```

문서만 수정한 경우:

```bash
cd website
npm run typecheck
npm run build
```

## 관련 문서

- [Trace Learning Loop](../concepts/trace-learning.md)
- [Suggestions](./suggestions.md)
- [Scrubbing](./scrubbing.md)
- [Quality Lab](../validation/quality-lab.md)
- [Search Tuning](../search/search-tuning.md)
