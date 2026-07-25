---
title: Quality Lab
description: Run search, plan, and execute cases against a collection before enabling production usage.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Quality Lab

Quality Lab is the product-facing validation layer for API collections. It runs
repeatable cases through search, target selection, plan synthesis, and optional
execution.

Use it before enabling an API collection for real Planflow usage. It should
answer four questions:

1. Can search find the right target family?
2. Can target selection choose the correct final tool?
3. Can plan synthesis fill or request the required inputs?
4. Can execution reach the downstream API safely?

## Validation Flow

Quality Lab should be run as a staged gate. Do not start with live execution if
search or plan evidence is not stable.

| Stage | Input | Output | Stop If |
| --- | --- | --- | --- |
| Build | OpenAPI/MCP/Python sources | collection artifact, readiness report | schema coverage is too low |
| Search | query cases | Top-K rows and evidence | expected target is absent |
| Select | Top-K + optional LLM target | `target_selector` block | selector is ambiguous for critical cases |
| Plan | selected target + entities | `Plan`, slots, diagnostics | required fields are unsatisfied |
| Execute | plan + adapter auth | runner events and assertions | auth or mutation safety fails |
| Learn | scrubbed result | suggestions and shadow rank | payload scrubbing fails |

This keeps failures classified by stage instead of collapsing everything into a
single "agent failed" result.

## Case Modes

| Mode | Purpose | Typical Gate |
| --- | --- | --- |
| `search` | Check retrieval and Top-K behavior | expected target is in Top-K |
| `plan` | Check target selection and plan synthesis | selected target and plan tools match expectations |
| `execute` | Run the plan through the adapter when safe | HTTP result and assertions pass |

Search and plan cases should run frequently. Execute cases should run only when
auth readiness and mutation safety are understood.

## Case Schema

<Tabs>
  <TabItem value="search" label="Search" default>

```json
{
  "id": "member-search-001",
  "mode": "search",
  "query": "Find member delivery detail",
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
  "query": "Find the member delivery detail",
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
  "query": "Find the member delivery detail",
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

Fields are intentionally additive. Existing search-only cases should keep
working when plan or execute fields are added.

## Result Shape

A useful Quality Lab result should preserve each stage as a separate object.

| Section | Purpose |
| --- | --- |
| `search` | Top-K results, hit position, score breakdown |
| `target_selector` | LLM target, selected target, override flag, reason codes |
| `plan` | plan id, steps, user input slots, synthesis diagnostics |
| `execute` | runner events, HTTP status, latency, assertions |
| `auth_readiness` | structured auth preflight state |
| `learning` | suggestions created or shadow-applied |
| `failure` | stable failure reason and failed stage |

Example:

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

Mutating execute cases should require:

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

If a case cannot meet those requirements, keep it in `search` or `plan` mode.
Read-only execution is still an adapter operation and should go through auth
readiness before calling the downstream API.

## Auth Readiness

Execute mode should distinguish preflight failures from real API failures.

| Reason | Meaning |
| --- | --- |
| `auth_context_required` | No usable runtime user/session context |
| `auth_profile_missing` | Collection requires auth but has no auth profile |
| `auth_header_resolution_failed` | Adapter could not resolve execution headers |
| `auth_failed` | Downstream API returned 401 or 403 |

Do not store raw tokens, cookies, user ids, or generated auth header values in
Quality Lab results. Store header names and structured reason codes only.

## Recommended Suites

Start with small suites and expand only when the signal is stable.

| Suite | Purpose | Suggested Cadence |
| --- | --- | --- |
| `search_core_30` | Search cases from real OpenAPI summaries | every search/semantic change |
| `business_manual_20` | Representative business queries written by operators | every release candidate |
| `plan_e2e_10` | Target selection and plan synthesis cases | every plan/selector change |
| `execute_read_5` | Read-only execution cases with auth readiness | dev deployment smoke |
| `execute_mutation_3` | Dev-only mutation cases with cleanup | manual or gated CI only |

## Acceptance Metrics

Metrics should be collection-specific, but a healthy large API collection should
track:

| Metric | What It Shows |
| --- | --- |
| search hit@K | whether retrieval keeps the correct tool visible |
| search Top-1 | whether the first candidate is usually correct |
| target selector accuracy | whether deterministic guardrails help rather than hide failure |
| plan hit rate | whether selected targets become executable plans |
| execute read success rate | whether adapter/auth/request execution works |
| structured failure rate | whether failures are classified instead of becoming 500s |
| latency by stage | where runtime is spent |

Public quality claims should include the dataset, model when applicable, run
configuration, and stored result artifact.

## Promotion Policy

Use Quality Lab results as a promotion gate for search tuning and trace
learning.

| Change Type | Required Evidence |
| --- | --- |
| alias or semantic metadata | search suite improves or stays stable |
| selector override policy | plan cases show correct final target |
| contract extraction change | readiness and contract coverage improve |
| learning suggestion promotion | shadow result improves and scrub check passes |
| execute enablement | auth readiness and read-only assertions pass |

Do not promote a change because one manual query looked better. Keep the failing
and fixed evidence side by side.

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| Search passes but plan fails | Required fields are unsatisfied | `plan.user_input_slots`, IO contracts |
| Plan passes but execute fails | Auth or request adapter issue | `auth_readiness`, runner events |
| LLM target differs from selected target | Strong selector evidence overrode or ambiguity was detected | `target_selector.reason_codes` |
| Execute returns 401/403 | Runtime auth reached the API but was rejected | auth profile and downstream API policy |
| Results improve in shadow only | Learning suggestion is not promoted | promotion policy and Quality Lab approval |
| Execute succeeds but assertions fail | API reached but returned the wrong shape | response schema and assertion paths |

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Evidence Output](../search/evidence-output.md)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
