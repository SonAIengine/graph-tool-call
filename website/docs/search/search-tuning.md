---
title: Search Tuning
description: Improve retrieval quality with aliases, semantic metadata, contracts, and validation gates.
---

# Search Tuning

Tune search by improving catalog evidence before changing prompts.

Search tuning should be measurable. Before changing weights or prompts, export
a small query suite and record Top-K hits, selector decisions, and evidence for
misses.

## Order Of Operations

1. Check `semantic_summary`.
2. Check contract coverage.
3. Inspect top misses with `include_evidence=True`.
4. Add generic aliases through options.
5. Add manual edges only when deterministic evidence is not enough.
6. Promote trace-learning suggestions only after validation.
7. Re-run the search gate.

## Tuning Surface

| Surface | When To Use | Evidence |
| --- | --- | --- |
| semantic metadata | actions/resources/shapes are unknown | `semantic_summary` |
| IO contracts | producers or required fields are missing | `api_contract` coverage |
| aliases | domain language differs from OpenAPI names | paired query tests |
| candidate expansion | plan fails with missing producers | `unsatisfied_field` count |
| selector policy | correct tool is in Top-K but final target is wrong | `target_selector.rank_signals` |
| learning suggestions | repeated successful traces are stable | promoted suggestion records |

## Diagnostic Loop

```text
choose query suite
  -> run retrieval with evidence
  -> classify misses
  -> improve metadata/contract/aliases
  -> re-run same suite
  -> promote only repeatable improvements
```

Miss categories:

| Category | Meaning | Likely Fix |
| --- | --- | --- |
| `not_retrieved` | expected target is outside Top-K | semantic metadata or aliases |
| `low_rank` | expected target is present but weak | score signal or sibling control |
| `wrong_shape` | list/detail/count/mutation mismatch | result shape derivation |
| `producer_missing` | target found, plan cannot fill fields | contract extraction |
| `selector_mismatch` | LLM chose a weaker sibling | target selector evidence |

## Weight Changes

Use weight changes last. They affect the whole catalog and can hide bad
metadata. Prefer local, explainable evidence first:

- better `canonical_action`
- better `primary_resource`
- better `result_shape`
- cleaner `path_module`
- generic aliases
- promoted trace evidence

## Avoid

- hard-coding product-specific operation names in the engine
- boosting raw descriptions until noisy specs dominate results
- treating a single successful run as permanent ranking truth
- using a broad weight change to fix one query
- declaring improvement from only one manual query

## Acceptance Gates

A tuning change should report at least:

- query count
- Top-1 hit rate
- Top-3 or Top-8 hit rate
- average candidate count
- max candidate count
- selector override count
- uncaught error count

For XGEN-style collections, also track plan hit rate and `unsatisfied_field`
count because search quality is only useful if planning can use the target.

## Related Pages

- [Validation Benchmarks](../validation/benchmarks.md)
- [Learning Loop](../learning/shadow-promotion.md)
- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
