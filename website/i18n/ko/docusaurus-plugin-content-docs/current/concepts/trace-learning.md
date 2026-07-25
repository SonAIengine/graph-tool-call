---
title: Trace 학습 루프
description: LLM을 학습시키지 않고 scrub된 실행 trace로 search, target selection, planning을 개선합니다.
---

# Trace 학습 루프

Trace learning은 LLM 자체를 fine-tuning하지 않고 실행 이력에서 retrieval, target
selection, planning을 개선합니다.

첫 목표는 모델을 학습시키는 것이 아닙니다. 첫 목표는 실제 실행에서 안전한
collection-scoped evidence를 모으고, shadow mode에서 비교한 뒤, 반복적으로 도움이 되는
evidence만 promotion하는 것입니다.

## Mental Model

```text
run attempt
  -> scrub payload
  -> build learning record
  -> derive suggestions
  -> keep suggestions in shadow
  -> validate with repeated success or Quality Lab
  -> promote
  -> retrieval and target selector sees low-weight evidence
```

LLM은 나중에 더 좋은 후보와 metadata를 보게 됩니다. 이 loop가 LLM 자체를 변경하지는
않습니다.

## 왜 Fine-Tuning보다 먼저인가

대형 API collection의 초기 실패는 대부분 evidence 문제입니다.

- 정답 tool이 Top-K 안에서 너무 낮게 rank됨
- sibling tool의 action, resource, result-shape metadata가 약함
- selector가 왜 특정 target을 선호해야 하는지 설명하지 못함
- required field가 producer와 연결되지 않음
- auth failure가 request/API failure와 분리되지 않음
- 성공한 retry가 search나 plan evidence로 돌아오지 않음

Trace learning은 LLM이 받는 graph와 selector signal을 개선해서 이 문제들을 줄입니다.
Fine-tuning은 나중에, 학습할 만한 깨끗한 evidence가 쌓인 뒤 검토하는 편이 맞습니다.

## Public API

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
    summarize_learning_state,
)
```

이 API는 storage-neutral입니다. graph-tool-call은 record, suggestion, summary, optional
ranking signal을 만들고, adapter는 저장 위치와 promotion 시점을 결정합니다.

## Learning Record

Search, plan, execute attempt가 끝난 뒤 `build_trace_learning_record()`를 호출합니다.

```python
record = build_trace_learning_record(
    query="주문 상세를 보여줘",
    collection_id="orders-api",
    attempt_id="attempt_001",
    session_id="runtime-session-id",
    selected_target="getOrderDetail",
    llm_target="getOrderInfo",
    plan_tools=["findOrder", "getOrderDetail"],
    failure_reason=None,
    success=True,
    latency_ms=842,
    target_selector={
        "selected_target": "getOrderDetail",
        "overrode_llm": True,
        "reason_codes": ["llm_target_overridden"],
    },
    trace_edges=[
        {
            "source": "findOrder",
            "target": "getOrderDetail",
            "data_flow": {"to_field": "orderNo"},
        }
    ],
)
```

반환되는 record는 JSON-safe하고 compact합니다.

| Field | 목적 |
| --- | --- |
| `query` | scrub된 사용자 query |
| `query_family` | 유사 query를 묶는 normalized key |
| `query_fingerprint` | query family의 stable hash |
| `collection_id` | collection-local scope |
| `attempt_id` | attempt 식별자 |
| `session_id_hash` | raw 값이 아닌 hashed session id |
| `selected_target` | 최종 선택된 tool |
| `llm_target` | LLM이 제안한 target |
| `plan_tools` | 성공했거나 시도한 plan tool 순서 |
| `failure_reason` | stable reason code |
| `success` | attempt 성공 여부 |
| `latency_ms` | end-to-end latency |
| `target_selector` | scrub된 selector diagnostic |
| `trace_edges` | scrub된 run-observed graph edge evidence |
| `created_at` | ISO timestamp |

raw request body, raw response body, token, cookie, API key, 명백한 개인정보는 저장하지
않습니다.

## Scrubbing Boundary

모든 record field는 `scrub_trace_payload()`를 통과합니다.

```python
clean = scrub_trace_payload(
    {
        "Authorization": "Bearer secret-token",
        "email": "person@example.com",
        "response_body": {"orderNo": "1234"},
    }
)
```

예시 출력:

```json
{
  "Authorization": "[REDACTED]",
  "email": "[REDACTED_EMAIL]",
  "response_body": "[REDACTED]"
}
```

Scrubbing은 data science transformation이 아니라 safety boundary입니다. Payload를
안전하게 compact할 수 없다면 learning record를 거절해야 합니다.

## Suggestion Types

`derive_learning_suggestions()`는 성공 record를 improvement 후보로 바꿉니다.

| Suggestion Type | 의미 | 주로 쓰는 곳 |
| --- | --- | --- |
| `target_preference` | 이 query family에서 특정 target이 반복 선택됨 | retrieval과 target selector |
| `plan_path` | 이 plan path가 실제로 동작함 | plan synthesis |
| `data_flow_edge` | runtime trace가 tool 간 field flow를 보여줌 | graph expansion과 planner |
| `field_mapping` | field mapping 후보를 검토해야 함 | adapter 또는 operator UI |
| `context_default_candidate` | context default로 user-input prompt를 줄일 수 있음 | adapter settings |
| `enum_mapping_candidate` | enum label/value mapping이 유용할 수 있음 | adapter settings |

현재 helper는 앞의 세 가지를 직접 생성합니다. 나머지는 adapter가 검토된 signal을 같은
contract로 저장할 수 있도록 public suggestion vocabulary에 포함되어 있습니다.

## Suggestion Lifecycle

```text
suggested
  -> promotable
  -> promoted
  -> used as low-weight retrieval/selector evidence

suggested
  -> rejected
  -> ignored by retrieval/selector
```

기본 promotion policy는 보수적입니다.

| Policy Field | 기본값 | 의미 |
| --- | --- | --- |
| `min_success_observations` | `2` | suggestion이 promotable이 되기 전에 반복 성공 필요 |
| `max_recent_failure_ratio` | `0.5` | 불안정한 query family의 evidence 승격 방지 |
| `max_attempts` | `50` | 최근 attempt 저장 bound |
| `max_suggestions` | `100` | suggestion 저장 bound |

Adapter는 `promotable`을 `promoted`로 바꾸기 전에 사람 승인 단계를 요구할 수 있습니다.

## Derive Suggestions

```python
from graph_tool_call.learning import derive_learning_suggestions

suggestions = derive_learning_suggestions(
    record,
    history=previous_attempts,
    existing_suggestions=current_suggestions,
    promotion_policy={"min_success_observations": 2},
)
```

반환된 suggestion은 global이 아니라 collection 아래에 저장하세요. 한 API collection에서
학습된 target preference가 다른 collection으로 새면 안 됩니다.

## Apply Learning Signals

Learning boost는 optional이며 낮은 가중치입니다.

```python
from graph_tool_call.learning import apply_learning_suggestions

ranked = apply_learning_suggestions(
    "주문 상세를 보여줘",
    candidates=[
        {"name": "getOrderInfo", "score": 0.41},
        {"name": "getOrderDetail", "score": 0.39},
    ],
    suggestions=collection_learning["suggestions"],
    mode="promoted",
)
```

예시 signal:

```json
{
  "source": "learning",
  "target": "getOrderDetail",
  "suggestion_type": "target_preference",
  "status": "promoted",
  "observations": 3,
  "score": 0.045
}
```

`mode="promoted"`에서는 promoted suggestion만 ranking에 영향을 줍니다. Shadow 분석은
`mode="shadow"`로 suggested/promotable evidence를 비교하되 production behavior를 바꾸지
않습니다.

## Collection Storage Shape

Product adapter는 collection graph artifact 아래에 learning을 저장할 수 있습니다.

```json
{
  "learning": {
    "attempts": [],
    "suggestions": [],
    "promotion_policy": {
      "min_success_observations": 2,
      "max_recent_failure_ratio": 0.5
    },
    "summary": {
      "attempt_count": 0,
      "success_rate": null,
      "promoted_count": 0
    }
  }
}
```

작은 UI/API summary는 `summarize_learning_state()`로 만들 수 있습니다.

## Observe, Shadow, Promote

| Mode | 동작 | Production Ranking 변경 |
| --- | --- | --- |
| observe | attempt와 suggestion만 기록 | no |
| shadow | learning을 적용한 결과를 비교용으로 계산 | no |
| promoted | promoted suggestion이 low-weight signal로 들어감 | yes |

이 경계 덕분에 운 좋게 성공한 단일 실행이 곧바로 미래 behavior를 강하게 바꾸지 않습니다.

## Quality Lab Integration

Quality Lab은 원래 결과와 learning-shadowed 결과를 같이 저장해야 합니다.

| Metric | 의미 |
| --- | --- |
| `learning_suggestions_created` | run에서 생성된 suggestion |
| `learning_applied_shadow_rank` | shadow suggestion을 적용했을 때 rank |
| `promotion_status` | `suggested`, `promotable`, `promoted`, `rejected` |
| `target_rank_delta` | learning이 expected target을 위로 올렸는지 |

Quality Lab 또는 반복 real run이 개선을 증명한 뒤에만 promotion합니다.

## Adapter Boundary

graph-tool-call은 record와 suggestion contract를 정의합니다. Product adapter는 아래를
책임집니다.

- persistence
- retention policy
- operator approval
- collection-level isolation
- auth/session resolution
- promote/reject UI control
- shadow 또는 promoted mode 적용 여부

엔진에는 raw credential이나 사용자 식별값을 넣지 않습니다.

## Troubleshooting

| 증상 | 확인할 것 | 보완 |
| --- | --- | --- |
| suggestion이 생성되지 않음 | record `success`와 `selected_target` | 성공 run에서 learning record를 생성하는지 확인 |
| suggestion이 promotable이 되지 않음 | matching query fingerprint와 success count | query normalization과 history retention 확인 |
| learning이 rank를 너무 세게 바꿈 | `mode`, `max_boost`, suggestion status | `promoted` mode만 사용하고 boost를 낮춤 |
| learning JSON에 민감 문자열이 보임 | `scrub_trace_payload` test | record 거절 후 scrub rule 추가 |
| shadow에서는 target이 좋아지는데 production은 그대로임 | promotion status | gate 통과 후 승인 또는 promotion |

## 검증

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/ -q -k "learning or quality_lab or target_selector"
```

문서만 수정한 경우:

```bash
cd website
npm run typecheck
npm run build
```

## 관련 문서

- [Scrubbing](../learning/scrubbing.md)
- [Suggestions](../learning/suggestions.md)
- [Shadow And Promotion](../learning/shadow-promotion.md)
- [Target Selection](../search/target-selection.md)
- [Evidence Output](../search/evidence-output.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
