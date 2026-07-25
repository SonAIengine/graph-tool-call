---
title: Scrubbing
description: Remove secrets and sensitive values before storing trace learning evidence.
---

# Scrubbing

Trace learning starts with payload scrubbing. The engine should store compact
evidence, not raw request or response payloads.

## Public API

```python
from graph_tool_call.learning import scrub_trace_payload

safe_payload = scrub_trace_payload(raw_payload)
```

## Values To Remove

- authorization headers
- cookies
- API keys
- tokens
- user ids
- emails and phone-like values
- raw request and response bodies

## Related Pages

- [Trace Learning](../concepts/trace-learning.md)
- [Shadow And Promotion](./shadow-promotion.md)
