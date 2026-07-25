---
title: Quality Lab
description: Run search, plan, and execute cases against a collection before enabling production usage.
---

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

## Case Modes

| Mode | Purpose | Typical Gate |
| --- | --- | --- |
| `search` | Check retrieval and Top-K behavior | expected target is in Top-K |
| `plan` | Check target selection and plan synthesis | selected target and plan tools match expectations |
| `execute` | Run the plan through the adapter when safe | HTTP result and assertions pass |

Search and plan cases should run frequently. Execute cases should run only when
auth readiness and mutation safety are understood.

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

Fields are intentionally additive. Existing search-only cases should keep
working when plan or execute fields are added.

## Execute Safety

Mutating execute cases should require:

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

If a case cannot meet those requirements, keep it in `search` or `plan` mode.

## Auth Readiness

Execute mode should distinguish preflight failures from real API failures:

| Reason | Meaning |
| --- | --- |
| `auth_context_required` | No usable runtime user/session context |
| `auth_profile_missing` | Collection requires auth but has no auth profile |
| `auth_header_resolution_failed` | Adapter could not resolve execution headers |
| `auth_failed` | Downstream API returned 401 or 403 |

Do not store raw tokens, cookies, user ids, or generated auth header values in
Quality Lab results. Store header names and structured reason codes only.

## Result Shape

A useful Quality Lab result should include:

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

Start with small suites and expand only when the signal is stable:

| Suite | Purpose |
| --- | --- |
| `search_core_30` | Search cases from real OpenAPI summaries |
| `business_manual_20` | Representative business queries written by operators |
| `plan_e2e_10` | Target selection and plan synthesis cases |
| `execute_read_5` | Read-only execution cases with auth readiness |
| `execute_mutation_3` | Dev-only mutation cases with cleanup |

## Acceptance Metrics

Metrics should be collection-specific, but a healthy large API collection should
track:

- search hit@8
- search Top-1
- target selector override accuracy
- plan hit rate
- execute read success rate
- structured auth failure rate
- uncaught server error count
- latency by stage

Public quality claims should include the dataset, model when applicable, run
configuration, and stored result artifact.

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| Search passes but plan fails | Required fields are unsatisfied | `plan.user_input_slots`, IO contracts |
| Plan passes but execute fails | Auth or request adapter issue | `auth_readiness`, runner events |
| LLM target differs from selected target | Strong selector evidence overrode or ambiguity was detected | `target_selector.reason_codes` |
| Execute returns 401/403 | Runtime auth reached the API but was rejected | auth profile and downstream API policy |
| Results improve in shadow only | Learning suggestion is not promoted | promotion policy and Quality Lab approval |

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
