---
title: Auth Readiness
description: missing auth context, auth profile 문제, 실제 API 인증 실패를 분리합니다.
---

# Auth Readiness

Auth readiness는 선택된 tool을 현재 product session과 collection auth profile로
실행할 수 있는지 설명합니다.

## Engine Role

엔진은 OpenAPI `security`와 contract field에서 auth requirement를 식별할 수
있습니다. raw token, cookie, API key, user id, session header는 저장하지 않습니다.

## Adapter Role

Adapter는 runtime auth context를 해석하고 structured readiness를 보고합니다.

| Field | Meaning |
| --- | --- |
| `required` | auth가 필요한지 |
| `source` | OpenAPI security, contract auth field, collection policy |
| `auth_profile_id_present` | collection에 auth profile이 있는지 |
| `xgen_auth_token_present` | runtime auth token 존재 여부, 값은 로그 금지 |
| `xgen_user_id_present` | user context 존재 여부, 값은 로그 금지 |
| `session_station_attempted` | runtime header 조회 여부 |
| `session_station_header_names` | header 이름만 |
| `failure_reason` | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed`, `auth_failed` |

## 관련 문서

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN API Collection](../guides/xgen-integration.md)
