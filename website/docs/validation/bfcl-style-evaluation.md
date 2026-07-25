---
title: BFCL-Style Evaluation
description: Document how graph-tool-call can be evaluated with tool-call benchmark methodology.
---

# BFCL-Style Evaluation

BFCL-style evaluation should be used when making public claims about tool-call
quality. It is heavier than the fast development loop and should run near
release candidates or benchmark claim updates.

## What To Measure

- target selection correctness
- plan validity
- argument readiness
- execution outcome when safe
- failure classification
- latency and token context budget

## What To Avoid

Do not publish benchmark numbers from narrow smoke tests. A public claim should
link to the dataset, model, run configuration, and stored result artifact.

## Related Pages

- [Benchmarks](./benchmarks.md)
- [Release Gates](./release-gates.md)
