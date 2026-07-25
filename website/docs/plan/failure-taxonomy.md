---
title: Failure Taxonomy
description: Classify search, target, plan, auth, request, API, cleanup, and learning failures.
---

# Failure Taxonomy

Failures should be structured. A product should not collapse every failed run
into "the agent failed."

The taxonomy is used by Planflow events, Quality Lab results, logs, and trace
learning records. The goal is to make the next action obvious: improve search
metadata, repair a contract, ask for user input, configure auth, retry the
downstream API, or reject a learning suggestion.

## Mental Model

A tool-call workflow fails at a stage, for a reason, with evidence. Keep those
three fields separate.

| Field | Meaning | Example |
| --- | --- | --- |
| `stage` | Where the failure happened | `synthesize`, `auth_preflight`, `execute` |
| `reason` | Stable machine-readable reason code | `unsatisfied_field`, `auth_context_required` |
| `evidence` | Compact proof used for debugging | missing field, selected target, HTTP status |

Do not use the exception message as the contract. Messages can change; reason
codes should remain stable.

## Failure Lifecycle

| Stage | Typical Reason Codes | Usually Fixed By |
| --- | --- | --- |
| `retrieve` | `no_candidates`, `not_retrieved`, `low_confidence` | semantic metadata, aliases, OpenAPI summaries, graph edges |
| `select_target` | `llm_target_mismatch`, `llm_target_not_in_candidates`, `ambiguous_target`, `selector_mismatch` | target selector evidence, result shape, contract fit, LLM catalog prompt |
| `synthesize` | `unknown_target`, `unsatisfied_field`, `enum_required`, `dynamic_option_required`, `cycle`, `max_depth`, `user_input_fallback` | IO contracts, producer edges, context defaults, user input UX |
| `bind_request` | `binding_failed`, `argument_coercion_failed`, `missing_required_argument` | schema contract, field mapping, runtime argument builder |
| `auth_preflight` | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed` | collection auth profile, product session, session header resolver |
| `execute` | `auth_failed`, `http_4xx`, `http_5xx`, `timeout`, `network_error` | downstream API, request construction, credentials, retry policy |
| `cleanup` | `cleanup_failed`, `cleanup_not_configured` | Quality Lab mutation case owner |
| `learn` | `scrub_failed`, `promotion_rejected`, `insufficient_repeated_success` | trace scrubbing, promotion policy, human review |
| `service` | `uncaught_server_error` | adapter or service bug |

The engine only owns product-neutral stages. Product adapters may add transport
or UI-specific stages, but they should preserve `stage`, `reason`, and compact
evidence.

## Engine Synthesis Errors

`PathSynthesizer` raises `PlanSynthesisError` and subclasses for synthesis
failures. Adapters should call `to_dict()` instead of parsing exception strings.

```python
from graph_tool_call.plan import PathSynthesizer, PlanSynthesisError

synthesizer = PathSynthesizer(graph_artifact)

try:
    plan = synthesizer.synthesize(
        target="getOrderDetail",
        goal="show me the order detail",
        entities={},
    )
except PlanSynthesisError as exc:
    diagnostic = exc.to_dict()
    # {"stage": "synthesize", "reason": "unsatisfied_field", ...}
```

`to_dict()` returns a stable envelope:

```json
{
  "stage": "synthesize",
  "reason": "unsatisfied_field",
  "message": "required field cannot be supplied",
  "field_name": "orderNo",
  "semantic_tag": "order_id",
  "target_tool": "getOrderDetail"
}
```

The exact detail keys depend on the reason. Treat extra fields as additive.

## Reason Code Catalog

### Search and Selection

| Reason | Meaning | Evidence To Store | Common Action |
| --- | --- | --- | --- |
| `no_candidates` | Retrieval returned no usable tools | query, filters, top_k | inspect catalog build and index coverage |
| `not_retrieved` | Expected target was absent from Top-K | expected target, returned tool names | improve semantic metadata or aliases |
| `low_confidence` | Candidate scores are too weak | score distribution, threshold | widen Top-K or add evidence |
| `llm_target_mismatch` | LLM chose a target different from the expected target | LLM target, expected target, selected target | inspect target selector diagnostics |
| `llm_target_not_in_candidates` | LLM chose a tool outside the retrieved catalog | LLM target, candidate names | pass selector-ranked catalog to the LLM |
| `ambiguous_target` | Multiple tools had similar evidence | margin, tied candidates | ask for clarification or preserve LLM target |
| `selector_mismatch` | Deterministic selector selected the wrong target | rank signals, override flag | tune generic selector policy or metadata |

### Plan Synthesis

| Reason | Meaning | Evidence To Store | Common Action |
| --- | --- | --- | --- |
| `unknown_target` | Target tool is not in the graph artifact | target tool, graph version | rebuild artifact or repair target selection |
| `unsatisfied_field` | Required consume field cannot be filled | field name, semantic tag, target tool | add producer edge, context default, or user slot |
| `enum_required` | Required enum field has no selected value | field name, enum values if safe | map enum labels or ask user |
| `dynamic_option_required` | A producer can fetch runtime options for a missing field | producer name, options path, label hints | show option picker before final plan |
| `cycle` | Tool dependency chain revisits a tool | chain, tool name | inspect graph edges and producer ranking |
| `max_depth` | Dependency search exceeded synthesizer depth | max depth, current tool | reduce graph noise or increase depth deliberately |
| `user_input_fallback` | Planner continued by asking the user for a value | field name, required flag | add UX slot or context default |

### Auth and Execution

| Reason | API Called? | Meaning | Common Action |
| --- | --- | --- | --- |
| `auth_context_required` | no | Auth is required but no runtime user/session context exists | run from logged-in UI or service account |
| `auth_profile_missing` | no | Collection/tool requires auth but has no auth profile | configure collection auth profile |
| `auth_header_resolution_failed` | no | Profile exists but adapter could not build headers | inspect session header resolver |
| `auth_failed` | yes | Downstream API returned 401 or 403 | refresh credentials or inspect downstream policy |
| `http_4xx` | yes | Downstream API rejected the request | inspect request arguments and business validation |
| `http_5xx` | yes | Downstream API failed server-side | retry only if safe; inspect API logs |
| `timeout` | maybe | Request exceeded timeout | inspect timeout, pagination, downstream latency |
| `network_error` | maybe | Transport failed before a useful HTTP response | inspect DNS, TLS, proxy, or allowlist |

### Quality Lab and Learning

| Reason | Meaning | Common Action |
| --- | --- | --- |
| `cleanup_failed` | Mutating validation case did not restore state | fix cleanup step before enabling the case |
| `cleanup_not_configured` | Mutating execute case has no cleanup plan | keep case disabled or add cleanup |
| `scrub_failed` | Trace payload could not be safely compacted | reject learning record |
| `insufficient_repeated_success` | Suggestion has not met promotion threshold | keep in shadow mode |
| `promotion_rejected` | Human or policy rejected a suggestion | store rejection reason, do not apply boost |

## Normalized Failure Record

Adapters should normalize failures into a compact record before writing Quality
Lab results, logs, or learning attempts.

```json
{
  "stage": "synthesize",
  "reason": "unsatisfied_field",
  "message": "Required field orderNo cannot be supplied",
  "tool": "getOrderDetail",
  "plan_id": "plan_01HZ...",
  "step_id": null,
  "retryable": false,
  "operator_action": "ask_user_or_add_context_default",
  "evidence": {
    "field_name": "orderNo",
    "semantic_tag": "order_id",
    "target_tool": "getOrderDetail"
  }
}
```

Use `retryable` carefully. Auth header refresh, network errors, and 5xx responses
may be retryable. Missing user input, missing auth profile, and unsupported
contracts usually are not retryable without a product action.

## Runner Event Example

Runner events are transport-neutral data. XGEN-style adapters often forward
`dataclasses.asdict(event)` to SSE, logs, and Quality Lab results.

```json
{
  "type": "step.failed",
  "stage": "execute",
  "plan_id": "plan_01HZ...",
  "step_id": "step_2",
  "tool": "getOrderDetail",
  "graph_tool_call_version": "0.32.1",
  "trace_metadata": {
    "failure_reason": "http_4xx",
    "http_status": 400,
    "auth_readiness": {
      "required": true,
      "auth_profile_id_present": true,
      "session_station_header_names": ["Authorization"],
      "failure_reason": null
    }
  }
}
```

The event may contain additional fields. Consumers should read only the fields
they understand and preserve unknown metadata when forwarding.

## Security Boundary

Failure records must never store raw credentials or personal data. Persist only
booleans, header names, field paths, statuses, and scrubbed values.

| Do Store | Do Not Store |
| --- | --- |
| `xgen_auth_token_present: true` | bearer token value |
| `session_station_header_names: ["Authorization"]` | `Authorization: Bearer ...` |
| `field_name: "orderNo"` | raw order response body |
| `http_status: 403` | cookie or API key |
| `session_id_hash` | raw user id, email, phone number |

This boundary is important because failure records are later used as trace
learning input.

## Triage Guide

| Symptom | Check First | Likely Fix |
| --- | --- | --- |
| Expected tool is not in Top-K | retrieval evidence and semantic metadata | improve aliases, summaries, contracts, or graph edges |
| Expected tool is in Top-K but not selected | `target_selector.rank_signals` and LLM target | improve action/resource/shape evidence or selector policy |
| Plan asks for an obvious field | `api_contract.consumes`, producer edges, context defaults | add context default, field mapping, or producer |
| Execute is blocked before API call | `auth_readiness.failure_reason` | configure auth profile or session header resolution |
| API returns 401/403 | downstream request header names and auth profile freshness | refresh auth or inspect downstream policy |
| API returns 400 | rendered request arguments | fix schema binding, enum mapping, or user input |
| Write case succeeds but leaves data | cleanup result | add cleanup assertion before allowing mutation |
| Failure turns into repeated success later | learning attempts and suggestions | keep suggestion shadowed until promotion gate passes |

## Quality Lab Assertions

Quality Lab should assert failure reasons, not just pass/fail booleans.

```json
{
  "mode": "execute",
  "query": "show order detail",
  "expected_target": "getOrderDetail",
  "assertions": {
    "selected_target": "getOrderDetail",
    "allowed_failure_reasons": [
      "auth_context_required",
      "auth_failed",
      "http_4xx"
    ],
    "uncaught_server_error": false
  }
}
```

This makes incomplete environments useful. A dev collection without credentials
can still prove that search and plan work, while execution fails with a known
auth reason instead of a server error.

## Validation

Use failure taxonomy assertions in runner, plan, auth, and Quality Lab tests:

```bash
poetry run pytest tests/ -q -k "failure or quality_lab or runner or auth"
```

For documentation-only changes, also run:

```bash
cd website
npm run typecheck
npm run build
```

## Related Pages

- [Auth Readiness](../build/auth-readiness.md)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](./plan-synthesis.md)
- [Runner Events](./runner-events.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
