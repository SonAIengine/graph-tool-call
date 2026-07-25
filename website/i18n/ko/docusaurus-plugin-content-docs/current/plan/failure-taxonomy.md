---
title: 실패 분류
description: search, target, plan, auth, request, API, cleanup failure를 분류합니다.
---

# 실패 분류

실패는 구조화되어야 합니다. product는 모든 실패를 "agent 실패" 하나로 뭉개면
안 됩니다.

이 taxonomy는 Planflow event, Quality Lab result, log, learning record에서 사용됩니다.
목표는 다음 액션을 분명하게 만드는 것입니다. retrieval을 고칠지, metadata를 보강할지,
사용자 입력을 요청할지, auth를 설정할지, downstream API를 조사할지 바로 보여야 합니다.

## Common Classes

| Class | Reason Codes | 일반적인 Owner |
| --- | --- | --- |
| Search failure | `no_candidates`, `not_retrieved`, `low_confidence` | catalog/search tuning |
| Target failure | `llm_target_mismatch`, `ambiguous_target`, `selector_mismatch` | selector policy 또는 metadata |
| Plan failure | `unknown_target`, `unsatisfied_field`, `enum_required`, `cycle`, `max_depth` | planner 또는 missing input |
| User input | `user_input_fallback`, `dynamic_option_required` | product UX |
| Auth readiness | `auth_context_required`, `auth_profile_missing`, `auth_header_resolution_failed` | adapter/auth 설정 |
| API auth | `auth_failed` | runtime credential 또는 downstream auth |
| HTTP failure | `http_4xx`, `http_5xx` | downstream API 또는 request construction |
| Cleanup failure | `cleanup_failed` | Quality Lab mutating case owner |
| Service failure | `uncaught_server_error` | adapter/service bug |

## 왜 중요한가

각 class는 수정 방법이 다릅니다. Search failure는 catalog evidence를 고쳐야 하고,
auth readiness failure는 adapter 설정을 봐야 하며, HTTP failure는 API나 request를
조사해야 합니다.

## Event Shape

Plan/runner event는 failure를 분류할 수 있는 metadata를 가져야 합니다.

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

adapter마다 event type은 조금 다를 수 있지만, `stage`, `tool`, stable reason code는
확인 가능해야 합니다.

## Triage Guide

| 증상 | 먼저 볼 것 | 보완 |
| --- | --- | --- |
| expected tool이 Top-K에 없음 | retrieval evidence와 semantic metadata | alias, summary, contract, graph edge 개선 |
| expected tool은 Top-K에 있는데 선택 안 됨 | selector rank signal과 LLM target | action/resource/shape evidence 또는 selector policy 개선 |
| obvious field인데 사용자 입력 요청 | `api_contract.consumes`와 context default | context default 또는 field mapping 추가 |
| API 호출 전 execute 차단 | auth readiness block | auth profile/session header resolution 설정 |
| API가 401/403 반환 | downstream request header | auth refresh 또는 profile 점검 |
| write case가 data를 남김 | cleanup result | mutation case 전에 cleanup assertion 추가 |

## Learning Boundary

learning record에는 failure class와 compact evidence만 저장하고 raw payload는 저장하지
않습니다. 실패 run은 scrub된 뒤, 나중에 성공한 retry 또는 human-approved correction과
연결될 때만 유용한 evidence가 됩니다.

## 검증

Quality Lab과 runner test에는 failure taxonomy assertion을 둡니다.

```bash
poetry run pytest tests/ -q -k "failure or quality_lab or runner"
```

## 관련 문서

- [Auth Readiness](../build/auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
- [Runner Events](./runner-events.md)
- [Trace Learning](../concepts/trace-learning.md)
