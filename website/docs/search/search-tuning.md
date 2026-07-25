---
title: Search Tuning
description: Improve retrieval quality with aliases, semantic metadata, contracts, and validation gates.
---

# Search Tuning

Tune search by improving catalog evidence before changing prompts.

## Order Of Operations

1. Check `semantic_summary`.
2. Check contract coverage.
3. Inspect top misses with `include_evidence=True`.
4. Add generic aliases through options.
5. Add manual edges only when deterministic evidence is not enough.
6. Promote trace-learning suggestions only after validation.
7. Re-run the search gate.

## Avoid

- hard-coding product-specific operation names in the engine
- boosting raw descriptions until noisy specs dominate results
- treating a single successful run as permanent ranking truth

## Related Pages

- [Validation Benchmarks](../validation/benchmarks.md)
- [Learning Loop](../learning/shadow-promotion.md)
