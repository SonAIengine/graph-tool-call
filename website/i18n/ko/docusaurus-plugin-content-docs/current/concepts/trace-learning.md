---
title: Trace 학습 루프
description: LLM을 학습시키지 않고 scrub된 실행 trace로 검색과 planning을 개선합니다.
---

# Trace 학습 루프

Trace learning loop는 LLM 자체를 fine-tuning하지 않고, collection 실행 이력에서
retrieval, target selection, planning에 필요한 evidence를 축적하는 방식입니다.

엔진은 성공한 target, plan path, data-flow edge, 구조화된 실패 reason을 collection
단위로 저장합니다. 이후 LLM은 바뀐 모델이 아니라 더 좋은 후보와 metadata를 보고
판단합니다.

## Mental Model

```text
run attempt
  -> scrub payload
  -> build learning record
  -> derive suggestions
  -> shadow compare
  -> promote after validation
  -> retrieval/selector sees low-weight evidence
```

## 저장하는 것

Learning record는 compact하고 scrub된 fact만 저장합니다.

| Field | 목적 |
| --- | --- |
| `query` | scrub된 사용자 query |
| `query_family` | 유사 query를 묶는 normalized key |
| `query_fingerprint` | query family의 stable hash |
| `collection_id` | collection-local scope |
| `attempt_id` | 실행 attempt 식별자 |
| `session_id_hash` | raw session 값이 아닌 hash |
| `selected_target` | 최종 선택된 tool |
| `llm_target` | LLM이 제안한 target |
| `plan_tools` | 시도했거나 성공한 plan tool 순서 |
| `failure_reason` | 안정적인 실패 reason |
| `success` | attempt 성공 여부 |
| `latency_ms` | end-to-end latency |
| `target_selector` | scrub된 selector diagnostic |
| `trace_edges` | scrub된 run-observed graph edge evidence |

raw request/response body, token, cookie, API key, 명백한 개인정보는 저장하지 않습니다.

## 왜 먼저 LLM을 학습시키지 않는가

대형 API collection의 초기 실패는 대부분 모델 지식 문제가 아니라 catalog evidence
문제입니다.

- 정답 tool이 Top-K 안에서 너무 낮게 rank됩니다.
- sibling tool의 action/resource/shape metadata가 약합니다.
- required field가 producer와 매핑되지 않았습니다.
- auth readiness가 빠져 있습니다.
- 실행 실패가 search, plan, auth, HTTP 중 어디인지 분류되지 않습니다.

Trace learning은 LLM이 보는 graph evidence를 개선해서 이 문제들을 줄입니다.

## Suggestion Flow

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
)

record = build_trace_learning_record(
    query=query,
    collection_id=collection_id,
    selected_target=selected_target,
    plan_tools=plan_tools,
    success=True,
)

suggestions = derive_learning_suggestions(record, history=attempts)
```

## Adapter Boundary

graph-tool-call은 record와 suggestion contract를 정의합니다. product adapter는 저장
위치, promotion policy, operator 승인, auth/user/session 세부 정보를 책임집니다.
엔진에는 raw credential이나 사용자 식별값을 넣지 않습니다.

## 관련 문서

- [Scrubbing](../learning/scrubbing.md)
- [Suggestions](../learning/suggestions.md)
- [Shadow And Promotion](../learning/shadow-promotion.md)
- [Evidence Output](../search/evidence-output.md)
