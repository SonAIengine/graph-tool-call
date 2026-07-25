---
title: 실패 분류
description: search, target, plan, auth, request, API, cleanup, learning failure를 분류합니다.
---

# 실패 분류

실패는 구조화되어야 합니다. product는 모든 실패를 "agent 실패" 하나로 뭉개면
안 됩니다.

이 taxonomy는 Planflow event, Quality Lab result, log, trace learning record에서
사용됩니다. 목표는 다음 액션을 분명하게 만드는 것입니다. search metadata를 고칠지,
contract를 repair할지, 사용자 입력을 요청할지, auth를 설정할지, downstream API를
재시도할지, learning suggestion을 거절할지 바로 보여야 합니다.

## Mental Model

Tool-call workflow의 실패는 stage, reason, evidence로 나누어 봅니다. 이 셋을
섞지 않는 것이 핵심입니다.

| Field | 의미 | 예시 |
| --- | --- | --- |
| `stage` | 실패가 발생한 위치 | `synthesize`, `auth_preflight`, `execute` |
| `reason` | 안정적인 machine-readable reason code | `unsatisfied_field`, `auth_context_required` |
| `evidence` | 디버깅에 필요한 compact proof | missing field, selected target, HTTP status |

Exception message를 계약으로 쓰지 마세요. 메시지는 바뀔 수 있지만 reason code는
안정적으로 유지되어야 합니다.

## Failure Lifecycle

| Stage | 대표 Reason Codes | 보통 수정하는 곳 |
| --- | --- | --- |
| `retrieve` | `no_candidates`, `not_retrieved`, `low_confidence` | semantic metadata, alias, OpenAPI summary, graph edge |
| `select_target` | `llm_target_mismatch`, `llm_target_not_in_candidates`, `ambiguous_target`, `selector_mismatch` | target selector evidence, result shape, contract fit, LLM catalog prompt |
| `synthesize` | `unknown_target`, `unsatisfied_field`, `enum_required`, `dynamic_option_required`, `cycle`, `max_depth`, `user_input_fallback` | IO contract, producer edge, context default, user input UX |
| `bind_request` | `binding_failed`, `argument_coercion_failed`, `missing_required_argument` | schema contract, field mapping, runtime argument builder |
| `auth_preflight` | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed` | collection auth profile, product session, session header resolver |
| `execute` | `auth_failed`, `http_4xx`, `http_5xx`, `timeout`, `network_error` | downstream API, request construction, credential, retry policy |
| `cleanup` | `cleanup_failed`, `cleanup_not_configured` | Quality Lab mutation case owner |
| `learn` | `scrub_failed`, `promotion_rejected`, `insufficient_repeated_success` | trace scrubbing, promotion policy, human review |
| `service` | `uncaught_server_error` | adapter 또는 service bug |

엔진은 product-neutral stage만 책임집니다. Product adapter는 transport나 UI-specific
stage를 추가할 수 있지만, `stage`, `reason`, compact evidence는 보존해야 합니다.

## Engine Synthesis Errors

`PathSynthesizer`는 synthesis 실패 시 `PlanSynthesisError`와 하위 exception을
발생시킵니다. Adapter는 exception 문자열을 파싱하지 말고 `to_dict()`를 호출해야
합니다.

```python
from graph_tool_call.plan import PathSynthesizer, PlanSynthesisError

synthesizer = PathSynthesizer(graph_artifact)

try:
    plan = synthesizer.synthesize(
        target="getOrderDetail",
        goal="주문 상세를 보여줘",
        entities={},
    )
except PlanSynthesisError as exc:
    diagnostic = exc.to_dict()
    # {"stage": "synthesize", "reason": "unsatisfied_field", ...}
```

`to_dict()`는 안정적인 envelope을 반환합니다.

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

detail key는 reason에 따라 달라질 수 있습니다. 새 field는 additive로 취급하세요.

## Reason Code Catalog

### Search and Selection

| Reason | 의미 | 저장할 Evidence | 일반적인 조치 |
| --- | --- | --- | --- |
| `no_candidates` | retrieval이 사용할 tool을 반환하지 못함 | query, filter, top_k | catalog build와 index coverage 점검 |
| `not_retrieved` | 기대 target이 Top-K에 없음 | expected target, returned tool names | semantic metadata 또는 alias 보강 |
| `low_confidence` | candidate score가 약함 | score distribution, threshold | Top-K 확대 또는 evidence 추가 |
| `llm_target_mismatch` | LLM이 기대 target과 다른 tool을 고름 | LLM target, expected target, selected target | target selector diagnostic 확인 |
| `llm_target_not_in_candidates` | LLM이 retrieved catalog 밖의 tool을 고름 | LLM target, candidate names | selector-ranked catalog를 LLM에 전달 |
| `ambiguous_target` | 여러 tool의 evidence가 비슷함 | margin, tied candidates | 사용자 확인 또는 LLM target 유지 |
| `selector_mismatch` | deterministic selector가 잘못된 target을 선택함 | rank signals, override flag | generic selector policy 또는 metadata 조정 |

### Plan Synthesis

| Reason | 의미 | 저장할 Evidence | 일반적인 조치 |
| --- | --- | --- | --- |
| `unknown_target` | target tool이 graph artifact에 없음 | target tool, graph version | artifact rebuild 또는 target selection repair |
| `unsatisfied_field` | required consume field를 채울 수 없음 | field name, semantic tag, target tool | producer edge, context default, user slot 추가 |
| `enum_required` | required enum field 값이 선택되지 않음 | field name, safe enum values | enum label mapping 또는 사용자 선택 |
| `dynamic_option_required` | 누락 field의 runtime option을 가져올 producer가 있음 | producer name, options path, label hints | 최종 plan 전에 option picker 표시 |
| `cycle` | tool dependency chain이 같은 tool을 다시 방문함 | chain, tool name | graph edge와 producer ranking 점검 |
| `max_depth` | dependency search가 synthesizer depth를 초과함 | max depth, current tool | graph noise를 줄이거나 depth를 의도적으로 조정 |
| `user_input_fallback` | planner가 사용자 입력 슬롯으로 계속 진행함 | field name, required flag | UX slot 또는 context default 추가 |

### Auth and Execution

| Reason | API 호출 여부 | 의미 | 일반적인 조치 |
| --- | --- | --- | --- |
| `auth_context_required` | no | auth가 필요하지만 runtime user/session context가 없음 | 로그인 UI 또는 service account에서 실행 |
| `auth_profile_missing` | no | collection/tool은 auth가 필요한데 profile이 없음 | collection auth profile 설정 |
| `auth_header_resolution_failed` | no | profile은 있지만 adapter가 header를 만들지 못함 | session header resolver 점검 |
| `auth_failed` | yes | downstream API가 401 또는 403 반환 | credential refresh 또는 downstream policy 점검 |
| `http_4xx` | yes | downstream API가 request를 거절함 | request argument와 business validation 확인 |
| `http_5xx` | yes | downstream API server-side 실패 | 안전할 때만 retry, API log 확인 |
| `timeout` | maybe | request가 timeout을 초과함 | timeout, paging, downstream latency 점검 |
| `network_error` | maybe | 유의미한 HTTP response 전에 transport 실패 | DNS, TLS, proxy, allowlist 확인 |

### Quality Lab and Learning

| Reason | 의미 | 일반적인 조치 |
| --- | --- | --- |
| `cleanup_failed` | mutating validation case가 상태를 원복하지 못함 | case 활성화 전에 cleanup step 수정 |
| `cleanup_not_configured` | mutating execute case에 cleanup plan이 없음 | case를 비활성으로 두거나 cleanup 추가 |
| `scrub_failed` | trace payload를 안전하게 compact하지 못함 | learning record 거절 |
| `insufficient_repeated_success` | promotion threshold를 아직 만족하지 못함 | shadow mode 유지 |
| `promotion_rejected` | 사람 또는 policy가 suggestion을 거절함 | rejection reason 저장, boost 적용 금지 |

## Normalized Failure Record

Adapter는 Quality Lab result, log, learning attempt에 저장하기 전에 실패를 compact
record로 정규화해야 합니다.

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

`retryable`은 신중하게 설정하세요. Auth header refresh, network error, 5xx response는
retry 가능할 수 있습니다. 사용자 입력 누락, auth profile 누락, unsupported contract는
product action 없이는 보통 retryable이 아닙니다.

## Runner Event Example

Runner event는 transport-neutral data입니다. XGEN 같은 adapter는 보통
`dataclasses.asdict(event)`를 SSE, log, Quality Lab result로 forwarding합니다.

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

Event에는 추가 field가 들어갈 수 있습니다. Consumer는 자신이 이해하는 field만 읽고,
알 수 없는 metadata는 forwarding할 때 보존하는 편이 안전합니다.

## Security Boundary

Failure record에는 raw credential이나 개인정보를 저장하면 안 됩니다. Boolean, header
name, field path, status, scrub된 value만 저장합니다.

| 저장 가능 | 저장 금지 |
| --- | --- |
| `xgen_auth_token_present: true` | bearer token value |
| `session_station_header_names: ["Authorization"]` | `Authorization: Bearer ...` |
| `field_name: "orderNo"` | raw order response body |
| `http_status: 403` | cookie 또는 API key |
| `session_id_hash` | raw user id, email, phone number |

이 boundary는 failure record가 나중에 trace learning input으로 쓰이기 때문에 특히
중요합니다.

## Triage Guide

| 증상 | 먼저 볼 것 | 보완 |
| --- | --- | --- |
| expected tool이 Top-K에 없음 | retrieval evidence와 semantic metadata | alias, summary, contract, graph edge 개선 |
| expected tool은 Top-K에 있는데 선택 안 됨 | `target_selector.rank_signals`와 LLM target | action/resource/shape evidence 또는 selector policy 개선 |
| obvious field인데 plan이 사용자 입력을 요청함 | `api_contract.consumes`, producer edge, context default | context default, field mapping, producer 추가 |
| API 호출 전에 execute가 차단됨 | `auth_readiness.failure_reason` | auth profile 또는 session header resolution 설정 |
| API가 401/403 반환 | downstream request header name과 auth profile freshness | auth refresh 또는 downstream policy 점검 |
| API가 400 반환 | rendered request argument | schema binding, enum mapping, user input 수정 |
| write case가 data를 남김 | cleanup result | mutation 허용 전에 cleanup assertion 추가 |
| 실패 후 재시도에서 반복 성공함 | learning attempt와 suggestion | promotion gate 통과 전까지 shadow 유지 |

## Quality Lab Assertions

Quality Lab은 pass/fail boolean만 보지 말고 failure reason을 assertion해야 합니다.

```json
{
  "mode": "execute",
  "query": "주문 상세를 보여줘",
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

이렇게 하면 credential이 없는 dev collection도 유용합니다. Search와 plan이 동작한다는
것을 증명하고, execute는 server error가 아니라 알려진 auth reason으로 실패해야 합니다.

## 검증

Runner, plan, auth, Quality Lab test에 failure taxonomy assertion을 둡니다.

```bash
poetry run pytest tests/ -q -k "failure or quality_lab or runner or auth"
```

문서만 수정한 경우에도 아래를 실행합니다.

```bash
cd website
npm run typecheck
npm run build
```

## 관련 문서

- [Auth Readiness](../build/auth-readiness.md)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](./plan-synthesis.md)
- [Runner Events](./runner-events.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
