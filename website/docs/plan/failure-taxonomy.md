---
title: Failure Taxonomy
description: Classify search, target, plan, auth, request, API, and cleanup failures.
---

# Failure Taxonomy

Failures should be structured. A product should not collapse every failure into
"the agent failed."

## Common Classes

| Class | Examples |
| --- | --- |
| Search failure | no candidates, low confidence, target not in Top-K |
| Target failure | LLM target mismatch, ambiguous target |
| Plan failure | unsatisfied field, enum required, cycle |
| Auth readiness | auth context required, auth profile missing |
| API auth | 401 or 403 from the downstream API |
| HTTP failure | 4xx or 5xx after auth is ready |
| Cleanup failure | mutating test cleanup did not complete |

## Why It Matters

Each class needs a different fix. Search failures need better catalog evidence.
Auth readiness failures need adapter configuration. HTTP failures need API or
request investigation.

## Related Pages

- [Auth Readiness](../build/auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
