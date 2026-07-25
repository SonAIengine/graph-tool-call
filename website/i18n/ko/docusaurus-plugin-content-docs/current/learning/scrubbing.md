---
title: Payload Scrubbing
description: trace learning evidence를 저장하기 전에 secret과 sensitive value를 제거합니다.
---

# Payload Scrubbing

Trace learning은 payload scrubbing에서 시작합니다. learning loop는 compact 실행
evidence를 저장할 수 있지만, raw API payload나 runtime credential을 저장하면 안
됩니다.

attempt, suggestion, runner metadata, product diagnostic을 저장하기 전에 항상
scrubbing을 적용합니다.

## Public API

```python
from graph_tool_call.learning import scrub_trace_payload

safe_payload = scrub_trace_payload(raw_payload)
```

이 helper는 dictionary, list, tuple, string을 재귀적으로 순회합니다. 민감해 보이는
값은 redact하고 긴 string은 truncate합니다.

## 제거할 값

| Pattern | 예시 |
| --- | --- |
| Secret-looking keys | `authorization`, `cookie`, `token`, `api_key`, `secret`, `password`, `session` |
| User id keys | `user_id`, `x-user-id` |
| Raw payload keys | `body`, `request_body`, `response_body`, `raw`, `payload`, `output`, `result` |
| Bearer token | `Bearer eyJ...` |
| JWT-like value | `eyJ...abc.def...` |
| Long hex secret | 32자 이상의 API key 또는 hash |
| Email value | `person@example.com` |
| Phone-like value | 공백이나 dash가 포함된 긴 숫자열 |

## 예시

```python
from graph_tool_call.learning import scrub_trace_payload

raw = {
    "headers": {
        "Authorization": "Bearer secret-token",
        "X-Trace-ID": "trace-001",
    },
    "response_body": {"customerEmail": "person@example.com"},
    "selected_target": "getCustomerDetail",
}

safe = scrub_trace_payload(raw)
```

`safe`는 debugging에 필요한 shape는 유지하면서 저장하면 안 되는 값을 redact합니다.

## 저장 정책

저장할 수 있는 값:

- collection id
- attempt id
- query family와 fingerprint
- selected target과 LLM target
- plan tool 이름
- 안정적인 failure reason
- latency
- selector signal
- scrub된 trace edge evidence

저장하지 않을 값:

- raw request body
- raw response body
- auth header value
- cookie value
- API key
- session token
- hash되지 않은 user identifier
- payload 내부의 개인값

## Adapter Guidance

Adapter는 log나 JSONB metadata에 쓰기 전에 scrub해야 합니다. product가 감사 목적으로
full request/response body를 보관해야 한다면 graph-tool-call artifact나 learning
suggestion이 아니라 별도의 보안 audit system에 저장합니다.

## 관련 문서

- [Trace Learning](../concepts/trace-learning.md)
- [Suggestions](./suggestions.md)
- [Shadow And Promotion](./shadow-promotion.md)
