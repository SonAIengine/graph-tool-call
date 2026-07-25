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

## Output Contract

Response synthesis is deliberately the last mile. It should never be the only
place where execution state is preserved.

| Input | Kept For | Notes |
| --- | --- | --- |
| `requirement` | user-facing context | use the original request, not a rewritten guess |
| `result` | success summary | project or compress large payloads first |
| `failed_step` | failure localization | prefer stable step ids when available |
| `error.reason_code` | product diagnostics | keep the structured code alongside the final answer |
| `partial_results` | useful progress | include only scrubbed, non-sensitive summaries |

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
- pass the same trace metadata to logs/SSE so the final answer can be audited

## Deterministic Fallback

Use a template instead of LLM synthesis when the answer must be strict JSON,
when compliance requires approved language, or when the failure reason is
already actionable. A common adapter pattern is:

```python
if response_format == "json" or error.reason_code in {"auth_failed", "auth_context_required"}:
    return deterministic_response(trace)

return synthesize_failure_response(..., llm=llm)
```

The key rule is that synthesis can make the answer easier to read, but it should
not invent missing totals, hide failed stages, or rewrite a structured reason
into a vague apology.

## Quality Checks

For real integrations, verify that success and failure answers preserve:

- the selected target tool
- `plan_id` and failed step, when present
- the reason code for structured failures
- truncation limits for large payloads
- absence of raw tokens, cookies, phone numbers, or internal ids

## When Not To Use It

Skip response synthesis when the product already has a strict response format,
when the result must be machine-readable JSON, or when compliance policy
requires a deterministic template.

## Related Pages

- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Event Schemas](../reference/event-schemas.md)
