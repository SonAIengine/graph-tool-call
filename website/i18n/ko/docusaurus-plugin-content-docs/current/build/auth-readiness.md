---
title: Auth Readiness
description: missing auth context, auth profile 문제, 실제 API 인증 실패를 분리합니다.
---

# Auth Readiness

Auth readiness는 선택된 tool을 현재 product session과 collection auth profile로
실행할 수 있는지 설명합니다.

서로 쉽게 섞이는 세 가지 상태를 분리합니다.

- OpenAPI collection은 auth가 필요한데 runtime context가 없음
- product에는 auth profile이 있지만 header를 만들 수 없음
- downstream API가 해석된 credential을 거부함

## Engine Role

엔진은 OpenAPI `security`와 contract field에서 auth requirement를 식별할 수
있습니다. raw token, cookie, API key, user id, session header는 저장하지 않습니다.

엔진은 structured requirement와 diagnostic만 내보냅니다. runtime credential lookup은
adapter의 책임입니다.

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

## Preflight Policy

실행 전에는 다음 순서로 처리합니다.

1. collection policy, OpenAPI `security`, contract auth field를 확인합니다.
2. auth가 필요하면 auth profile 또는 그에 준하는 adapter policy를 요구합니다.
3. 현재 product session에서 runtime header를 해석합니다.
4. trace metadata에는 boolean과 header 이름만 저장합니다.
5. preflight가 실패하면 downstream API를 호출하지 않습니다.

이렇게 해야 credential을 graph artifact나 log에 남기지 않으면서도 Quality Lab과 Planflow
실패를 진단할 수 있습니다.

## Failure Reason

| Reason | API 호출 여부 | 의미 |
| --- | --- | --- |
| `auth_context_required` | no | user/session context가 없음 |
| `auth_profile_missing` | no | collection/tool은 auth가 필요한데 profile이 없음 |
| `auth_header_resolution_failed` | no | profile은 있지만 runtime header 생성 실패 |
| `auth_failed` | yes | downstream API가 401/403 반환 |

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

이 구조에는 header 값을 절대 저장하지 않습니다.

## 검증

auth test는 동작과 scrubbing을 모두 증명해야 합니다.

```bash
poetry run pytest tests/ -q -k "auth_readiness or quality_lab"
```

## 관련 문서

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN API Collection](../guides/xgen-integration.md)
