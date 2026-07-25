---
title: Failure Taxonomy
description: Classify search, target, plan, auth, request, API, and cleanup failures.
---

# Failure Taxonomy

Failures should be structured. A product should not collapse every failure into
"the agent failed."

The taxonomy is used by Planflow events, Quality Lab results, logs, and learning
records. The goal is to make the next action obvious: improve retrieval, repair
metadata, request user input, configure auth, or inspect the downstream API.

## Common Classes

| Class | Reason Codes | Typical Owner |
| --- | --- | --- |
| Search failure | `no_candidates`, `not_retrieved`, `low_confidence` | catalog/search tuning |
| Target failure | `llm_target_mismatch`, `ambiguous_target`, `selector_mismatch` | selector policy or metadata |
| Plan failure | `unknown_target`, `unsatisfied_field`, `enum_required`, `cycle`, `max_depth` | planner or missing inputs |
| User input | `user_input_fallback`, `dynamic_option_required` | product UX |
| Auth readiness | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed` | adapter/auth configuration |
| API auth | `auth_failed` | runtime credentials or downstream auth |
| HTTP failure | `http_4xx`, `http_5xx` | downstream API or request construction |
| Cleanup failure | `cleanup_failed` | Quality Lab mutating case owner |
| Service failure | `uncaught_server_error` | adapter/service bug |

## Why It Matters

Each class needs a different fix. Search failures need better catalog evidence.
Auth readiness failures need adapter configuration. HTTP failures need API or
request investigation.

## Event Shape

Plan and runner events should carry enough metadata to classify the failure:

```json
{
  "type": "plan.failed",
  "stage": "plan_synthesis",
  "plan_id": "plan_01HZ...",
  "step_id": null,
  "tool": "getOrderDetail",
  "graph_tool_call_version": "0.32.1",
  "trace_metadata": {
    "failure_reason": "unsatisfied_field",
    "required_field": "orderNo"
  }
}
```

The exact event type may differ by adapter, but `stage`, `tool`, and a stable
reason code should remain available.

## Triage Guide

| Symptom | Check First | Likely Fix |
| --- | --- | --- |
| expected tool not in Top-K | retrieval evidence and semantic metadata | improve aliases, summaries, contracts, or graph edges |
| expected tool in Top-K but not selected | selector rank signals and LLM target | improve action/resource/shape evidence or selector policy |
| plan asks user for obvious field | `api_contract.consumes` and context defaults | add context default or field mapping |
| execute blocked before API call | auth readiness block | configure auth profile/session header resolution |
| API returns 401/403 | downstream request headers | refresh auth or inspect profile |
| write case succeeds but leaves data | cleanup result | add cleanup assertions before enabling mutation case |

## Learning Boundary

Learning records should store the failure class and compact evidence, not raw
payloads. A failed run can become useful evidence only after it is scrubbed and
linked to a later successful retry or a human-approved correction.

## Validation

Use failure taxonomy assertions in Quality Lab and runner tests:

```bash
poetry run pytest tests/ -q -k "failure or quality_lab or runner"
```

## Related Pages

- [Auth Readiness](../build/auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
- [Runner Events](./runner-events.md)
- [Trace Learning](../concepts/trace-learning.md)
