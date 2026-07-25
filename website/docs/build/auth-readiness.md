---
title: Auth Readiness
description: Separate missing auth context, auth profile problems, and real API authentication failures.
---

# Auth Readiness

Auth readiness explains whether a selected tool can be executed with the
available product session and collection auth profile.

It separates three different states that are easy to confuse:

- the OpenAPI collection requires auth but no runtime context exists
- the product has an auth profile but cannot resolve headers
- the downstream API rejected the resolved credentials

## Engine Role

The engine can identify auth requirements from OpenAPI `security` and contract
fields. It should not store raw tokens, cookies, API keys, user ids, or session
headers.

The engine should only emit structured requirements and diagnostics. Runtime
credential lookup belongs to the adapter.

## Adapter Role

The adapter should resolve runtime auth context and report structured readiness:

| Field | Meaning |
| --- | --- |
| `required` | Whether auth is required |
| `source` | OpenAPI security, contract auth field, or collection policy |
| `auth_profile_id_present` | Whether the collection has an auth profile |
| `xgen_auth_token_present` | Whether a runtime auth token exists, without logging the value |
| `xgen_user_id_present` | Whether user context exists, without logging the value |
| `session_station_attempted` | Whether runtime headers were requested |
| `session_station_header_names` | Header names only |
| `failure_reason` | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed`, or `auth_failed` |

## Preflight Policy

Before execution:

1. Inspect collection policy, OpenAPI `security`, and contract auth fields.
2. If auth is required, require an auth profile or equivalent adapter policy.
3. Resolve runtime headers from the current product session.
4. Store only booleans and header names in trace metadata.
5. If preflight fails, do not call the downstream API.

This keeps Quality Lab and Planflow failures diagnosable without leaking
credentials into graph artifacts or logs.

## Failure Reasons

| Reason | API Called? | Meaning |
| --- | --- | --- |
| `auth_context_required` | no | user/session context was unavailable |
| `auth_profile_missing` | no | collection/tool requires auth but has no profile |
| `auth_header_resolution_failed` | no | profile exists but runtime headers could not be built |
| `auth_failed` | yes | downstream API returned 401/403 |

## Trace Example

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

Never store header values in this structure.

## Validation

Auth tests should prove both behavior and scrubbing:

```bash
poetry run pytest tests/ -q -k "auth_readiness or quality_lab"
```

## Related Pages

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN API Collection](../guides/xgen-integration.md)
