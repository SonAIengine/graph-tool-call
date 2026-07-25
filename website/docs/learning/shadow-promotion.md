---
title: Shadow And Promotion
description: Apply trace learning safely through observe, shadow, and promote stages.
---

# Shadow And Promotion

The default learning policy is:

```text
observe -> shadow -> promote
```

This keeps the system from overfitting to a single lucky run. A successful trace
is evidence, not an immediate production rule.

## Modes

| Mode | Behavior | Ranking Impact |
| --- | --- | --- |
| Observe | Store scrubbed attempts and suggestions | none |
| Shadow | Compute learning-applied ranking beside current ranking | none on execution |
| Promoted | Apply validated low-weight signals | small additive boost |

## Observe

In observe mode, the adapter stores compact attempts and suggestions:

```python
record = build_trace_learning_record(...)
suggestions = derive_learning_suggestions(record, history=attempts)
```

Use observe mode when first enabling learning on a collection.

## Shadow

Shadow mode computes “what would have happened” if learning were active, but it
does not change the selected target or executed plan.

Track:

- current selected target
- shadow selected target
- current rank
- shadow rank
- whether the expected target would improve
- whether any failure would have been avoided

Shadow mode is the right default for dev and early production rollout.

## Promote

Only promoted suggestions affect retrieval and target selection.

Promotion should require at least one of:

- repeated success in the same query family
- Quality Lab validation
- operator approval
- a controlled rollout rule for a low-risk collection

## Promotion Gate

A suggestion should become promotable only when:

- the same query family succeeds repeatedly
- the same target or plan path is stable
- recent failure rate is acceptable
- scrubbing found no sensitive values
- Quality Lab or operator review approves it

## Failure Handling

Learning should also preserve failures. A failed attempt can prevent promotion,
explain why a plan path is risky, and help a product UI show whether the problem
was search, target selection, plan synthesis, auth, HTTP, cleanup, or assertion
failure.

## Related Pages

- [Suggestions](./suggestions.md)
- [Scrubbing](./scrubbing.md)
- [Search Tuning](../search/search-tuning.md)
