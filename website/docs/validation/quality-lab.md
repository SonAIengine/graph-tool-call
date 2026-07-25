---
title: Quality Lab
description: Run search, plan, and execute cases against a collection before enabling production usage.
---

# Quality Lab

Quality Lab is the product-facing validation layer for API collections. It runs
repeatable cases through search, target selection, plan synthesis, and optional
execution.

## Case Modes

| Mode | Purpose |
| --- | --- |
| `search` | Check retrieval and Top-K behavior |
| `plan` | Check target selection and plan synthesis |
| `execute` | Run the plan through the adapter when safe |

## Execute Safety

Mutating execute cases should require:

- explicit mutation allowance
- dev host allowlist
- cleanup steps
- assertions
- structured failure recording

## Related Pages

- [Failure Taxonomy](../plan/failure-taxonomy.md)
- [XGEN Quality Lab](../integrations/xgen-quality-lab.md)
