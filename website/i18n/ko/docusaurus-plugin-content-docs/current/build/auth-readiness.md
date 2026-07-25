---
title: Auth Readiness
description: runtime auth context 누락, auth profile 문제, header 생성 실패, downstream 인증 실패를 분리합니다.
---

# Auth Readiness

Auth readiness는 plan 실행 전에 한 가지 질문에 답합니다. 선택된 tool을 adapter가 가진
runtime credential로 실제 호출할 수 있는가?

대형 OpenAPI catalog는 search와 plan까지는 정상처럼 보이다가 execute 단계에서 product
session, auth profile, downstream API policy 문제로 실패하는 경우가 많습니다. 이 문서는
그 실패가 generic한 "agent 실패"가 되지 않도록 작은 diagnostic contract를 정의합니다.

## 무엇을 분리하는가

Auth readiness는 서로 쉽게 섞이는 네 가지 상태를 분리합니다.

| 상태 | API 호출 여부 | Failure Reason | 의미 |
| --- | --- | --- | --- |
| runtime context 없음 | no | `auth_context_required` | tool은 auth가 필요한데 request에 session, token, user context가 없음 |
| collection profile 없음 | no | `auth_profile_missing` | collection/tool은 auth가 필요한데 adapter가 사용할 auth profile이 없음 |
| profile로 header를 만들 수 없음 | no | `auth_header_resolution_failed` | profile은 있지만 session header resolver가 usable header를 못 만들었거나 에러 |
| downstream이 credential 거부 | yes | `auth_failed` | API 호출은 되었고 401 또는 403을 받음 |

앞의 세 가지는 preflight failure입니다. downstream API를 호출하면 안 됩니다.
`auth_failed`만 downstream service가 request를 본 상태입니다.

## Engine Boundary

graph-tool-call은 product-neutral 엔진입니다. 엔진은 아래 근거에서 auth requirement를
식별할 수 있습니다.

- OpenAPI `security`
- OpenAPI security scheme
- `api_contract.consumes` 중 `kind: "auth"` field
- adapter가 전달한 collection-level metadata

엔진은 credential을 해석하지 않습니다. raw token, cookie, API key, session identifier,
user identifier를 저장하면 안 됩니다. Runtime credential lookup은 product adapter의
책임입니다.

## Adapter Boundary

Adapter는 runtime auth resolution을 책임집니다.

| 책임 | 예시 |
| --- | --- |
| 현재 request context 확인 | 로그인 UI request, service account, scheduled job |
| collection auth profile 로드 | `auth_profile_id`, profile type, header strategy |
| session resolver에 header 요청 | session-station 또는 product auth service |
| preflight 통과 후 downstream API 호출 | HTTP executor에 scrub-safe header map 전달 |
| secret 없이 diagnostic 저장 | boolean, header name, failure reason |

XGEN에서는 로그인 사용자의 request header와 collection `auth_profile_id`를 downstream API
header로 바꾸는 지점이 여기에 해당합니다. 다른 product도 resolver만 다를 뿐 같은
contract를 사용할 수 있습니다.

## Readiness Object

Adapter는 Quality Lab result, runner trace metadata, log에 같은 구조를 붙이는 것이
좋습니다.

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

field는 확장할 수 있지만, 기존 의미는 안정적으로 유지해야 합니다.

| Field | 의미 |
| --- | --- |
| `required` | 선택된 tool 또는 collection에 auth가 필요한지 |
| `source` | auth가 필요한 이유. 예: `openapi.security`, `api_contract.auth`, `collection_policy` |
| `auth_profile_id_present` | collection에 auth profile 또는 그에 준하는 policy가 있는지 |
| `xgen_auth_token_present` | runtime auth token 존재 여부. 값은 저장하지 않음 |
| `xgen_user_id_present` | user context 존재 여부. 값은 저장하지 않음 |
| `session_station_attempted` | adapter가 runtime header resolution을 시도했는지 |
| `session_station_header_names` | header 이름만. 값은 금지 |
| `failure_reason` | 준비되었으면 null, 아니면 stable auth reason code |

Non-XGEN adapter도 이 shape를 유지할 수 있습니다. Product-specific source 이름은 내부에서
다르게 쓸 수 있지만 public graph artifact에는 generic하게 남기는 편이 좋습니다.

## Preflight Algorithm

`PlanRunner`나 downstream HTTP executor를 호출하기 전에 아래 순서로 처리합니다.

1. collection policy, OpenAPI `security`, contract auth field를 확인합니다.
2. auth가 필요 없으면 `required: false`를 남기고 계속 진행합니다.
3. auth가 필요한데 auth profile이 없으면 `auth_profile_missing`으로 중단합니다.
4. runtime session/token/user context가 없으면 `auth_context_required`로 중단합니다.
5. runtime auth resolver에 downstream header를 요청합니다.
6. resolver가 usable header를 반환하지 못하거나 에러면 `auth_header_resolution_failed`로 중단합니다.
7. `auth_readiness`에는 boolean과 header name만 저장합니다.
8. API를 호출합니다.
9. API가 401 또는 403을 반환하면 `auth_failed`로 분류합니다.

이 정책은 의도적으로 보수적입니다. auth context 누락은 product 상태 문제이지, 내부 API를
credential 없이 호출해도 된다는 신호가 아닙니다.

## Decision Table

| Auth Required | Profile Present | Runtime Context | Header Resolver | HTTP Status | Result |
| --- | --- | --- | --- | --- | --- |
| no | any | any | not needed | any | 정상 execute |
| yes | no | any | not attempted | none | `auth_profile_missing` |
| yes | yes | no | not attempted | none | `auth_context_required` |
| yes | yes | yes | empty or error | none | `auth_header_resolution_failed` |
| yes | yes | yes | headers returned | 401 or 403 | `auth_failed` |
| yes | yes | yes | headers returned | 2xx, 3xx, non-auth 4xx/5xx | HTTP/request policy로 분류 |

`auth_failed`는 `http_4xx`와 의도적으로 분리합니다. Business validation 때문에 발생한
400과 만료 token 때문에 발생한 401은 보완 액션이 다릅니다.

## Source Detection

Auth는 여러 위치에서 추론될 수 있습니다.

| Source | Signal | Notes |
| --- | --- | --- |
| OpenAPI operation security | operation-level `security` | 가장 강한 operation-specific source |
| OpenAPI global security | root `security` | operation override가 없으면 적용 |
| security schemes | bearer, apiKey, basic, OAuth2 | auth consume field 생성에 도움 |
| contract consumes | `kind: "auth"` | request builder가 쓰는 runtime contract |
| collection policy | adapter metadata | spec이 불완전할 때 유용 |

source가 서로 충돌하면 diagnostic에 근거를 모두 남깁니다. 실행 정책은 adapter가 가장
엄격한 쪽을 선택할 수 있습니다.

## Trace Metadata

Runner event에는 execution failure detail과 함께 auth readiness를 남겨야 합니다.

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

preflight에서 실패한 경우에도 `http_status`만 없을 뿐 같은 구조가 있어야 합니다.

## Security Rules

Auth diagnostic은 Quality Lab, log, learning record, UI panel로 복사되는 일이 많습니다.
항상 scrub-safe해야 합니다.

| 저장 가능 | 저장 금지 |
| --- | --- |
| `xgen_auth_token_present: true` | token value |
| `xgen_user_id_present: true` | raw user id |
| `session_station_header_names: ["Authorization"]` | `Authorization: Bearer ...` |
| `failure_reason: "auth_failed"` | cookie value |
| `source: "openapi.security"` | API key |

attempt를 연결해야 한다면 raw auth value 밖에서 만든 stable hash를 저장하세요. raw value를
log나 graph artifact에 넣지 않습니다.

## Quality Lab Usage

Quality Lab은 auth outcome을 구조화된 결과로 취급해야 합니다.

```json
{
  "mode": "execute",
  "query": "최근 주문을 찾아줘",
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

이렇게 하면 CI나 dev 환경에 human login session 또는 service account가 없어도 search와
plan 품질은 증명할 수 있습니다.

## UI Checklist

Integration UI는 사용자가 왜 실패했는지 추측하기 전에 실행 준비 상태를 보여줘야 합니다.

| UI Label | 조건 |
| --- | --- |
| 실행 가능 | `required=false` 또는 `failure_reason=null` |
| 로그인 컨텍스트 필요 | `failure_reason=auth_context_required` |
| 인증 프로필 없음 | `failure_reason=auth_profile_missing` |
| 인증 헤더 생성 실패 | `failure_reason=auth_header_resolution_failed` |
| API 인증 실패 | `failure_reason=auth_failed` |

브라우저에는 header 이름만 보여주세요. header 값은 절대 노출하지 않습니다.

## Troubleshooting

| 증상 | 확인할 것 | 보완 |
| --- | --- | --- |
| plan은 성공했는데 execute가 API를 호출하지 않음 | `auth_readiness.failure_reason` | profile 설정 또는 로그인 context에서 실행 |
| UI는 profile이 있다고 하는데 header가 비어 있음 | session resolver result와 profile type | auth profile refresh flow 수정 |
| header는 만들어졌는데 API가 401/403 반환 | downstream auth log와 profile freshness | token refresh 또는 scope 수정 |
| 일부 operation만 auth가 필요함 | operation-level `security` | build 시 per-tool auth metadata 보존 |
| learning record에 auth처럼 보이는 문자열이 있음 | trace scrubbing test | record 거절 후 scrubbing boundary 수정 |

## 검증

Auth test는 동작과 scrubbing을 모두 증명해야 합니다.

```bash
poetry run pytest tests/ -q -k "auth_readiness or quality_lab or execute"
```

문서만 수정한 경우에도 아래를 실행합니다.

```bash
cd website
npm run typecheck
npm run build
```

## 관련 문서

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [Runner Events](../plan/runner-events.md)
- [Quality Lab](../validation/quality-lab.md)
- [XGEN Integration](../guides/xgen-integration.md)
