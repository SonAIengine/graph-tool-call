---
title: Response Synthesis
description: Generate structured success and failure responses after tool execution.
---

# Response Synthesis

Response synthesis turns plan and runner output into the final assistant-facing
answer. It should summarize what happened without hiding stage, failed step, or
reason-code evidence.

The helpers use an `OntologyLLM` interface. The adapter decides which provider
and model to use.

## Public Helpers

```python
from graph_tool_call.plan import (
    synthesize_failure_response,
    synthesize_success_response,
)
```

## Success Response

```python
answer = synthesize_success_response(
    requirement="회원 배송지를 조회해줘",
    result=trace.output,
    llm=llm,
    result_char_limit=4000,
)
```

The success prompt is careful about counts. If the API result is truncated and
does not contain an explicit total field, the model should not claim an absolute
total.

## Failure Response

```python
answer = synthesize_failure_response(
    requirement="회원 배송지를 조회해줘",
    failed_step=trace.failed_step or "unknown",
    error={"reason_code": "auth_failed", "message": "HTTP 403"},
    partial_results=[step.output for step in trace.steps if step.error is None],
    llm=llm,
)
```

Failure responses should explain:

- what the user asked for
- what was attempted
- where it failed
- the plain-language reason
- what can be tried next, if obvious

## Adapter Guidance

Before calling response synthesis:

- project or compress large API payloads
- scrub sensitive values
- preserve `plan_id`, `failed_step`, and reason code
- keep raw audit payloads outside the engine

## When Not To Use It

Skip response synthesis when the product already has a strict response format,
when the result must be machine-readable JSON, or when compliance policy
requires a deterministic template.

## Related Pages

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Event Schemas](../reference/event-schemas.md)
