---
title: Auth Readiness
description: Separate missing runtime auth context, auth profile problems, header resolution, and downstream auth failures.
---

# Auth Readiness

Auth readiness answers one question before a plan is executed: can this selected
tool be called with the runtime credentials available to the adapter?

Large OpenAPI catalogs often look healthy at search and plan time, then fail at
execute time because the product session, auth profile, or downstream API policy
is not ready. This page defines a small diagnostic contract so those failures do
not become generic "agent failed" errors.

## What It Separates

Auth readiness separates four states that are easy to confuse.

| State | API Called? | Failure Reason | Meaning |
| --- | --- | --- | --- |
| no runtime context | no | `auth_context_required` | The tool needs auth, but the request has no usable session, token, or user context |
| no collection profile | no | `auth_profile_missing` | The collection/tool requires auth, but the adapter has no auth profile to resolve headers |
| profile cannot build headers | no | `auth_header_resolution_failed` | A profile exists, but the session header resolver returned no usable headers or errored |
| downstream rejected credentials | yes | `auth_failed` | The API call happened and returned 401 or 403 |

The first three are preflight failures. They should not call the downstream API.
Only `auth_failed` means the downstream service saw a request.

## Engine Boundary

graph-tool-call is product-neutral. It can identify auth requirements from:

- OpenAPI `security`
- OpenAPI security schemes
- `api_contract.consumes` fields with `kind: "auth"`
- collection-level metadata passed by an adapter

The engine should not resolve credentials. It should not store raw tokens,
cookies, API keys, session identifiers, or user identifiers. Runtime credential
lookup belongs to the product adapter.

## Adapter Boundary

The adapter owns runtime auth resolution:

| Responsibility | Example |
| --- | --- |
| detect current request context | logged-in UI request, service account, scheduled job |
| load collection auth profile | `auth_profile_id`, profile type, header strategy |
| ask session resolver for headers | session-station or product auth service |
| call downstream API only after preflight passes | HTTP executor receives scrub-safe header map |
| write diagnostics without secrets | booleans, header names, failure reason |

In XGEN, this is where the logged-in user's request headers and collection
`auth_profile_id` are converted into downstream API headers. Other products can
use the same contract with a different resolver.

## Readiness Object

Adapters should attach the same structure to Quality Lab results, runner trace
metadata, and logs.

```json
{
  "auth_readiness": {
    "required": true,
    "source": "openapi.security",
    "auth_profile_id_present": true,
    "xgen_auth_token_present": true,
    "xgen_user_id_present": true,
    "session_station_attempted": true,
    "session_station_header_names": ["Authorization", "X-User-ID"],
    "failure_reason": null
  }
}
```

The field names can be extended, but the existing meanings should remain stable.

| Field | Meaning |
| --- | --- |
| `required` | Whether the selected tool or collection requires auth |
| `source` | Why auth is required, such as `openapi.security`, `api_contract.auth`, or `collection_policy` |
| `auth_profile_id_present` | Whether the collection has an auth profile or equivalent policy |
| `xgen_auth_token_present` | Whether a runtime auth token exists, without storing the value |
| `xgen_user_id_present` | Whether user context exists, without storing the value |
| `session_station_attempted` | Whether the adapter attempted runtime header resolution |
| `session_station_header_names` | Header names only, never values |
| `failure_reason` | Null when ready, otherwise a stable auth reason code |

Non-XGEN adapters can keep the shape and rename product-specific internal
sources in their own code. Public graph artifacts should stay generic.

## Preflight Algorithm

Use this order before calling `PlanRunner` or the downstream HTTP executor.

1. Inspect collection policy, OpenAPI `security`, and contract auth fields.
2. If auth is not required, set `required: false` and continue.
3. If auth is required and no auth profile exists, stop with `auth_profile_missing`.
4. If no runtime session/token/user context exists, stop with `auth_context_required`.
5. Ask the runtime auth resolver for downstream headers.
6. If the resolver returns no usable headers or errors, stop with `auth_header_resolution_failed`.
7. Store only booleans and header names in `auth_readiness`.
8. Call the API.
9. If the API returns 401 or 403, classify the result as `auth_failed`.

This policy is intentionally conservative. A missing auth context is a product
state problem, not an invitation to call an internal API without credentials.

## Decision Table

| Auth Required | Profile Present | Runtime Context | Header Resolver | HTTP Status | Result |
| --- | --- | --- | --- | --- | --- |
| no | any | any | not needed | any | execute normally |
| yes | no | any | not attempted | none | `auth_profile_missing` |
| yes | yes | no | not attempted | none | `auth_context_required` |
| yes | yes | yes | empty or error | none | `auth_header_resolution_failed` |
| yes | yes | yes | headers returned | 401 or 403 | `auth_failed` |
| yes | yes | yes | headers returned | 2xx, 3xx, non-auth 4xx/5xx | classify by HTTP/request policy |

`auth_failed` is deliberately separate from `http_4xx`. A 400 from a business
validation rule is not the same remediation as a 401 from an expired token.

## Source Detection

Auth can be inferred from several places.

| Source | Signal | Notes |
| --- | --- | --- |
| OpenAPI operation security | operation-level `security` | strongest operation-specific source |
| OpenAPI global security | root `security` | applies unless operation overrides it |
| security schemes | bearer, apiKey, basic, OAuth2 | helps create auth consume fields |
| contract consumes | `kind: "auth"` | stable runtime contract for request builders |
| collection policy | adapter metadata | useful when spec is incomplete |

If sources disagree, keep all evidence in diagnostics. The adapter can choose
the strictest policy for execution.

## Trace Metadata

Runner events should carry auth readiness alongside execution failure details.

```json
{
  "type": "step.failed",
  "stage": "execute",
  "tool": "getMemberInfo",
  "trace_metadata": {
    "failure_reason": "auth_failed",
    "http_status": 403,
    "auth_readiness": {
      "required": true,
      "source": "openapi.security",
      "auth_profile_id_present": true,
      "xgen_auth_token_present": true,
      "xgen_user_id_present": true,
      "session_station_attempted": true,
      "session_station_header_names": ["Authorization"],
      "failure_reason": null
    }
  }
}
```

When preflight fails, the same structure should be present even though
`http_status` is absent.

## Security Rules

Auth diagnostics are often copied into Quality Lab, logs, learning records, and
UI panels. Keep them scrub-safe.

| Store | Do Not Store |
| --- | --- |
| `xgen_auth_token_present: true` | token value |
| `xgen_user_id_present: true` | raw user id |
| `session_station_header_names: ["Authorization"]` | `Authorization: Bearer ...` |
| `failure_reason: "auth_failed"` | cookie value |
| `source: "openapi.security"` | API key |

If you need to correlate attempts, store a stable hash generated outside the raw
auth value. Do not log the raw value and do not place it in graph artifacts.

## Quality Lab Usage

Quality Lab should treat auth outcomes as valid structured results.

```json
{
  "mode": "execute",
  "query": "find my recent orders",
  "expected_target": "getOrderList",
  "assertions": {
    "selected_target": "getOrderList",
    "allowed_failure_reasons": [
      "auth_context_required",
      "auth_profile_missing",
      "auth_header_resolution_failed",
      "auth_failed"
    ],
    "uncaught_server_error": false
  }
}
```

This lets CI and dev environments prove search and plan quality even when a
human login session or service account is unavailable.

## UI Checklist

An integration UI should show the execution readiness state before the user
wonders why a case failed.

| UI Label | Condition |
| --- | --- |
| Ready to execute | `required=false` or `failure_reason=null` |
| Login context required | `failure_reason=auth_context_required` |
| Auth profile missing | `failure_reason=auth_profile_missing` |
| Auth headers unavailable | `failure_reason=auth_header_resolution_failed` |
| API auth failed | `failure_reason=auth_failed` |

Show header names only. Never show header values in the browser.

## Troubleshooting

| Symptom | Inspect | Likely Fix |
| --- | --- | --- |
| Plan succeeds but execute does not call API | `auth_readiness.failure_reason` | configure profile or run from logged-in context |
| UI says profile exists but headers are empty | session resolver result and profile type | repair auth profile refresh flow |
| API returns 401/403 after headers resolve | downstream auth logs and profile freshness | refresh token or update scope |
| Only some operations require auth | operation-level `security` | preserve per-tool auth metadata during build |
| Learning record contains auth-looking strings | trace scrubbing tests | reject record and fix scrubbing boundary |

## Validation

Auth tests should prove behavior and scrubbing:

```bash
poetry run pytest tests/ -q -k "auth_readiness or quality_lab or execute"
```

For documentation-only changes, also run:

```bash
cd website
npm run typecheck
npm run build
```

## Related Pages

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [Runner Events](../plan/runner-events.md)
- [Quality Lab](../validation/quality-lab.md)
- [XGEN Integration](../guides/xgen-integration.md)
