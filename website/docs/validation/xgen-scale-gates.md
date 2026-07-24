# XGEN Scale Gates

XGEN scale gates replay large API collection snapshots so changes can be judged
against realistic catalog size.

## Gate Examples

- selector exact hit rate
- average candidate count
- max candidate count
- schema context reduction
- semantic action/resource/module coverage
- uncaught error count

## When To Run

- Run saved snapshot replay for everyday retrieval and selector changes.
- Run live scale sweep when OpenAPI ingest, search, semantic, or plan synthesis
  logic changes.
- Run full LLM E2E only for release candidates or public benchmark updates.

