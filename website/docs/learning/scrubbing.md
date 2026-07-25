---
title: Scrubbing
description: Remove secrets and sensitive values before storing trace learning evidence.
---

# Scrubbing

Trace learning starts with payload scrubbing. The learning loop is allowed to
store compact execution evidence, but it should not store raw API payloads or
runtime credentials.

Use scrubbing before saving attempts, suggestions, runner metadata, or product
diagnostics derived from execution.

## Public API

```python
from graph_tool_call.learning import scrub_trace_payload

safe_payload = scrub_trace_payload(raw_payload)
```

The helper recursively walks dictionaries, lists, tuples, and strings. Values
that look sensitive are redacted; long strings are truncated.

## What Gets Redacted

| Pattern | Example |
| --- | --- |
| Secret-looking keys | `authorization`, `cookie`, `token`, `api_key`, `secret`, `password`, `session` |
| User id keys | `user_id`, `x-user-id` |
| Raw payload keys | `body`, `request_body`, `response_body`, `raw`, `payload`, `output`, `result` |
| Bearer tokens | `Bearer eyJ...` |
| JWT-like values | `eyJ...abc.def...` |
| Long hex secrets | API keys or hashes with 32+ hex chars |
| Email values | `person@example.com` |
| Phone-like values | long digit groups with spaces or dashes |

## Example

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

`safe` keeps the shape useful for debugging, while redacting the values that
should not be persisted.

## Storage Policy

Store:

- collection id
- attempt id
- query family and fingerprint
- selected target and LLM target
- plan tool names
- stable failure reason
- latency
- selector signals
- scrubbed trace edge evidence

Do not store:

- raw request body
- raw response body
- auth header values
- cookie values
- API keys
- session tokens
- un-hashed user identifiers
- personal values found inside payloads

## Adapter Guidance

Adapters should scrub before writing to logs or JSONB metadata. If a product
needs full request/response bodies for audit, store them in a separate secured
audit system, not in graph-tool-call artifacts or learning suggestions.

## Related Pages

- [Trace Learning](../concepts/trace-learning.md)
- [Suggestions](./suggestions.md)
- [Shadow And Promotion](./shadow-promotion.md)
