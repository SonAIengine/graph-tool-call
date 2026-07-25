---
title: Scrubbing
description: trace learning evidence를 저장하기 전에 secret과 sensitive value를 제거합니다.
---

# Scrubbing

Trace learning은 payload scrubbing에서 시작합니다. 엔진은 raw request/response
payload가 아니라 compact evidence를 저장해야 합니다.

## Public API

```python
from graph_tool_call.learning import scrub_trace_payload

safe_payload = scrub_trace_payload(raw_payload)
```

## 제거할 값

- authorization header
- cookie
- API key
- token
- user id
- email/phone-like value
- raw request/response body

## 관련 문서

- [Trace Learning](../concepts/trace-learning.md)
- [Shadow And Promotion](./shadow-promotion.md)
