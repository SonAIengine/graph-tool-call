---
title: Quality Lab
description: production 사용 전에 collection 단위 search, plan, execute case를 실행합니다.
---

# Quality Lab

Quality Lab은 API collection을 위한 product-facing validation layer입니다. 반복 가능한
case를 search, target selection, plan synthesis, optional execution으로 실행합니다.

실제 Planflow 사용을 허용하기 전에 아래 네 가지 질문에 답해야 합니다.

1. search가 올바른 target family를 찾는가?
2. target selection이 정확한 final tool을 선택하는가?
3. plan synthesis가 required input을 채우거나 요청할 수 있는가?
4. execution이 downstream API까지 안전하게 도달하는가?

## Case Modes

| Mode | Purpose | Typical Gate |
| --- | --- | --- |
| `search` | retrieval과 Top-K behavior 확인 | expected target이 Top-K 안에 있음 |
| `plan` | target selection과 plan synthesis 확인 | selected target과 plan tools가 기대값과 일치 |
| `execute` | 안전할 때 adapter를 통해 plan 실행 | HTTP result와 assertion 통과 |

Search와 plan case는 자주 실행해야 합니다. Execute case는 auth readiness와 mutation
safety가 이해된 상태에서만 실행합니다.

## Case Schema

```json
{
  "id": "member-detail-001",
  "mode": "plan",
  "query": "Find the member delivery detail",
  "expected_target": "getMemberDeliveryDetail",
  "expected_top_k": 8,
  "provided_entities": {
    "memberNo": "sample-member"
  },
  "assertions": [
    {"type": "selected_target", "equals": "getMemberDeliveryDetail"}
  ],
  "mutation_safety": "read_only",
  "timeout_sec": 30
}
```

field는 additive하게 유지합니다. 기존 search-only case는 plan 또는 execute field가
추가되어도 계속 동작해야 합니다.

## Execute Safety

Mutating execute case는 아래 조건을 요구해야 합니다.

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

조건을 만족하지 못하는 case는 `search` 또는 `plan` mode로 유지합니다.

## Auth Readiness

Execute mode는 preflight failure와 실제 API failure를 분리해야 합니다.

| Reason | Meaning |
| --- | --- |
| `auth_context_required` | usable runtime user/session context 없음 |
| `auth_profile_missing` | collection에 auth가 필요하지만 auth profile 없음 |
| `auth_header_resolution_failed` | adapter가 execution header를 만들지 못함 |
| `auth_failed` | downstream API가 401 또는 403 반환 |

Quality Lab result에는 raw token, cookie, user id, generated auth header value를
저장하지 않습니다. header name과 structured reason code만 저장합니다.

## Result Shape

유용한 Quality Lab result는 아래 section을 포함해야 합니다.

| Section | Purpose |
| --- | --- |
| `search` | Top-K results, hit position, score breakdown |
| `target_selector` | LLM target, selected target, override flag, reason codes |
| `plan` | plan id, steps, user input slots, synthesis diagnostics |
| `execute` | runner events, HTTP status, latency, assertions |
| `auth_readiness` | structured auth preflight state |
| `learning` | suggestions created or shadow-applied |
| `failure` | stable failure reason and failed stage |

## Recommended Suites

작은 suite부터 시작하고 signal이 안정되면 확장합니다.

| Suite | Purpose |
| --- | --- |
| `search_core_30` | 실제 OpenAPI summary 기반 search case |
| `business_manual_20` | operator가 작성한 대표 business query |
| `plan_e2e_10` | target selection과 plan synthesis case |
| `execute_read_5` | auth readiness가 있는 read-only execution case |
| `execute_mutation_3` | cleanup이 있는 dev-only mutation case |

## Acceptance Metrics

metric은 collection별로 달라질 수 있지만, healthy large API collection은 아래를
추적해야 합니다.

- search hit@8
- search Top-1
- target selector override accuracy
- plan hit rate
- execute read success rate
- structured auth failure rate
- uncaught server error count
- latency by stage

public quality claim에는 dataset, applicable model, run configuration, stored result
artifact가 포함되어야 합니다.

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| Search는 통과하지만 plan 실패 | required field가 충족되지 않음 | `plan.user_input_slots`, IO contracts |
| Plan은 통과하지만 execute 실패 | auth 또는 request adapter 문제 | `auth_readiness`, runner events |
| LLM target과 selected target이 다름 | strong selector evidence override 또는 ambiguity | `target_selector.reason_codes` |
| Execute가 401/403 반환 | runtime auth가 API까지 갔지만 거절됨 | auth profile과 downstream API policy |
| shadow에서만 개선됨 | learning suggestion이 promoted되지 않음 | promotion policy와 Quality Lab approval |

## 관련 문서

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
