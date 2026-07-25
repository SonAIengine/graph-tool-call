---
title: Quality Gates
description: Validate search, target selection, plan, and execute changes with repeatable quality gates.
---

# Quality Gates

Quality gates keep search and planning improvements measurable.

Use gates to decide whether a change is ready for a release, not to prove that
every possible API call succeeds. A good gate makes both success and failure
diagnosable.

## Development Loop

Use quick deterministic checks during implementation:

```bash
make quick
poetry run pytest tests/test_graphify_metadata.py tests/test_openapi_readiness.py -q
```

Use larger OpenAPI and LLM checks only when retrieval, selector, or plan logic
changes materially.

## Gate Levels

| Level | Purpose | Typical Commands |
| --- | --- | --- |
| quick | local contract and regression loop | `make quick` |
| docs | documentation typecheck/build/search index | `cd website && npm run build` |
| collection | OpenAPI readiness and search cases | Quality Lab or fixture replay |
| release | full lint/test/build and selected benchmarks | `make release-check` plus benchmark gate |

## Suggested Metrics

For large OpenAPI collections:

- semantic action known rate
- primary resource assigned rate
- path/module assigned rate
- search Hit@K
- plan target hit rate
- execute read success rate
- structured failure classification rate
- uncaught server error count

The goal is not to make every API call succeed in CI. The goal is to make every
success and failure explainable.

## Acceptance Record

Keep a compact record for each gate run:

```json
{
  "gate": "xgen-scale-semantic",
  "version": "0.32.1",
  "case_count": 50,
  "search_hit_at_8": 1.0,
  "plan_hit_rate": 0.86,
  "uncaught_server_errors": 0,
  "artifact": "/tmp/gtc-quality-gate.json"
}
```

## Failure Taxonomy

Failures should be classified before the gate result is interpreted:

| Failure | Meaning |
| --- | --- |
| `not_retrieved` | expected tool not in candidate set |
| `selector_mismatch` | candidate exists but final target is wrong |
| `unsatisfied_field` | plan cannot fill a required value |
| `auth_context_required` | execution blocked before API call |
| `auth_failed` | downstream API rejected credentials |
| `http_4xx` / `http_5xx` | downstream API failure |
| `uncaught_server_error` | adapter or service bug |

## When To Run Expensive Gates

Run model-in-the-loop or live API gates when:

- retrieval/selector/plan logic changes
- public README or docs benchmark claims change
- release candidate is being cut
- a production incident points to ranking or planning quality

Use snapshot replay for ordinary docs or wording changes.

## Related Pages

- [Quality Lab](../validation/quality-lab.md)
- [Release Gates](../validation/release-gates.md)
- [BFCL-Style Evaluation](../validation/bfcl-style-evaluation.md)
