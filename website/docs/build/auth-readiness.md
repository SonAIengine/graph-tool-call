---
title: Auth Readiness
description: Separate missing auth context, auth profile problems, and real API authentication failures.
---

# Auth Readiness

Auth readiness explains whether a selected tool can be executed with the
available product session and collection auth profile.

## Engine Role

The engine can identify auth requirements from OpenAPI `security` and contract
fields. It should not store raw tokens, cookies, API keys, user ids, or session
headers.

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

## Related Pages

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN API Collection](../guides/xgen-integration.md)
