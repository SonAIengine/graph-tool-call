---
title: Quality Lab
description: production 사용 전에 collection 단위 search, plan, execute case를 실행합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Quality Lab

Quality Lab은 API collection을 위한 product-facing validation layer입니다. 반복 가능한
case를 search, target selection, plan synthesis, optional execution으로 실행합니다.

실제 Planflow 사용을 허용하기 전에 아래 네 가지 질문에 답해야 합니다.

1. search가 올바른 target family를 찾는가?
2. target selection이 정확한 final tool을 선택하는가?
3. plan synthesis가 required input을 채우거나 요청할 수 있는가?
4. execution이 downstream API까지 안전하게 도달하는가?

## Validation Flow

Quality Lab은 staged gate로 실행합니다. search 또는 plan evidence가 안정적이지 않은데
live execution부터 시작하지 않습니다.

| Stage | Input | Output | Stop If |
| --- | --- | --- | --- |
| Build | OpenAPI/MCP/Python source | collection artifact, readiness report | schema coverage가 너무 낮음 |
| Search | query case | Top-K row와 evidence | expected target이 없음 |
| Select | Top-K + optional LLM target | `target_selector` block | critical case에서 selector가 ambiguous |
| Plan | selected target + entity | `Plan`, slot, diagnostic | required field 미충족 |
| Execute | plan + adapter auth | runner event와 assertion | auth 또는 mutation safety 실패 |
| Learn | scrubbed result | suggestion과 shadow rank | payload scrubbing 실패 |

이렇게 나누면 모든 실패가 "agent failed" 하나로 뭉치지 않고 stage별로 분류됩니다.

## Case Modes

| Mode | Purpose | Typical Gate |
| --- | --- | --- |
| `search` | retrieval과 Top-K behavior 확인 | expected target이 Top-K 안에 있음 |
| `plan` | target selection과 plan synthesis 확인 | selected target과 plan tools가 기대값과 일치 |
| `execute` | 안전할 때 adapter를 통해 plan 실행 | HTTP result와 assertion 통과 |

Search와 plan case는 자주 실행해야 합니다. Execute case는 auth readiness와 mutation
safety가 이해된 상태에서만 실행합니다.

## Case Schema

<Tabs>
  <TabItem value="search" label="Search" default>

```json
{
  "id": "member-search-001",
  "mode": "search",
  "query": "회원 배송지 상세 정보를 찾아줘",
  "expected_target": "getMemberDeliveryDetail",
  "expected_top_k": 8,
  "assertions": [
    {"type": "top_k_contains", "tool": "getMemberDeliveryDetail", "k": 8}
  ]
}
```

  </TabItem>
  <TabItem value="plan" label="Plan">

```json
{
  "id": "member-plan-001",
  "mode": "plan",
  "query": "회원 배송지 상세 정보를 찾아줘",
  "expected_target": "getMemberDeliveryDetail",
  "provided_entities": {
    "memberNo": "sample-member"
  },
  "assertions": [
    {"type": "selected_target", "equals": "getMemberDeliveryDetail"},
    {"type": "plan_contains_tool", "tool": "getMemberDeliveryDetail"}
  ],
  "timeout_sec": 30
}
```

  </TabItem>
  <TabItem value="execute" label="Execute">

```json
{
  "id": "member-execute-001",
  "mode": "execute",
  "query": "회원 배송지 상세 정보를 찾아줘",
  "expected_target": "getMemberDeliveryDetail",
  "provided_entities": {
    "memberNo": "sample-member"
  },
  "mutation_safety": "read_only",
  "assertions": [
    {"type": "http_status", "in": [200]},
    {"type": "json_path_exists", "path": "$.data"}
  ],
  "timeout_sec": 30
}
```

  </TabItem>
</Tabs>

field는 additive하게 유지합니다. 기존 search-only case는 plan 또는 execute field가
추가되어도 계속 동작해야 합니다.

## Result Shape

유용한 Quality Lab result는 stage를 별도 object로 보존해야 합니다.

| Section | Purpose |
| --- | --- |
| `search` | Top-K results, hit position, score breakdown |
| `target_selector` | LLM target, selected target, override flag, reason codes |
| `plan` | plan id, steps, user input slots, synthesis diagnostics |
| `execute` | runner events, HTTP status, latency, assertions |
| `auth_readiness` | structured auth preflight state |
| `learning` | suggestions created or shadow-applied |
| `failure` | stable failure reason and failed stage |

예시:

```json
{
  "case_id": "member-plan-001",
  "mode": "plan",
  "status": "passed",
  "latency_ms": {
    "search": 42,
    "target_selection": 3,
    "plan": 914
  },
  "search": {
    "hit": true,
    "hit_rank": 1,
    "top_k": 8
  },
  "target_selector": {
    "llm_target": "getMemberDeliveryList",
    "selected_target": "getMemberDeliveryDetail",
    "overrode_llm": true,
    "reason_codes": ["llm_target_overridden", "selected_by_strong_evidence"]
  },
  "plan": {
    "status": "synthesized",
    "tools": ["getMemberDeliveryDetail"],
    "user_input_slots": []
  }
}
```

## Execute Safety

Mutating execute case는 아래 조건을 요구해야 합니다.

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

조건을 만족하지 못하는 case는 `search` 또는 `plan` mode로 유지합니다. Read-only execution도
adapter operation이므로 downstream API 호출 전에 auth readiness를 거쳐야 합니다.

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

## Recommended Suites

작은 suite부터 시작하고 signal이 안정되면 확장합니다.

| Suite | Purpose | Suggested Cadence |
| --- | --- | --- |
| `search_core_30` | 실제 OpenAPI summary 기반 search case | search/semantic 변경마다 |
| `business_manual_20` | operator가 작성한 대표 business query | release candidate마다 |
| `plan_e2e_10` | target selection과 plan synthesis case | plan/selector 변경마다 |
| `execute_read_5` | auth readiness가 있는 read-only execution case | dev deployment smoke |
| `execute_mutation_3` | cleanup이 있는 dev-only mutation case | manual 또는 gated CI only |

## Acceptance Metrics

metric은 collection별로 달라질 수 있지만, healthy large API collection은 아래를
추적해야 합니다.

| Metric | 보여주는 것 |
| --- | --- |
| search hit@K | retrieval이 correct tool을 후보군에 유지하는지 |
| search Top-1 | 첫 candidate가 보통 correct인지 |
| target selector accuracy | deterministic guardrail이 실패를 숨기지 않고 도움이 되는지 |
| plan hit rate | selected target이 executable plan이 되는지 |
| execute read success rate | adapter/auth/request execution이 동작하는지 |
| structured failure rate | failure가 500이 아니라 분류되는지 |
| latency by stage | runtime이 어디에서 쓰이는지 |

public quality claim에는 dataset, applicable model, run configuration, stored result
artifact가 포함되어야 합니다.

## Promotion Policy

Quality Lab result를 search tuning과 trace learning promotion gate로 사용합니다.

| Change Type | Required Evidence |
| --- | --- |
| alias 또는 semantic metadata | search suite가 개선되거나 유지됨 |
| selector override policy | plan case에서 correct final target 확인 |
| contract extraction change | readiness와 contract coverage 개선 |
| learning suggestion promotion | shadow result 개선 + scrub check 통과 |
| execute enablement | auth readiness와 read-only assertion 통과 |

manual query 하나가 좋아졌다는 이유로 promote하지 않습니다. 실패 evidence와 fixed evidence를
나란히 보존합니다.

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| Search는 통과하지만 plan 실패 | required field가 충족되지 않음 | `plan.user_input_slots`, IO contracts |
| Plan은 통과하지만 execute 실패 | auth 또는 request adapter 문제 | `auth_readiness`, runner events |
| LLM target과 selected target이 다름 | strong selector evidence override 또는 ambiguity | `target_selector.reason_codes` |
| Execute가 401/403 반환 | runtime auth가 API까지 갔지만 거절됨 | auth profile과 downstream API policy |
| shadow에서만 개선됨 | learning suggestion이 promoted되지 않음 | promotion policy와 Quality Lab approval |
| Execute는 성공했지만 assertion 실패 | API는 도달했지만 wrong shape 반환 | response schema와 assertion path |

## 관련 문서

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Evidence Output](../search/evidence-output.md)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
