---
title: Shadow And Promotion
description: Apply trace learning safely through observe, shadow, and promote stages.
---

# Shadow And Promotion

The default learning policy is observe, shadow, then promote.

## Modes

| Mode | Behavior |
| --- | --- |
| Observe | Store scrubbed trace records only |
| Shadow | Calculate learning-applied rankings without changing execution |
| Promoted | Apply validated low-weight boosts to retrieval and target selection |

## Promotion Gate

A suggestion should become promotable only when:

- the same query family succeeds repeatedly
- the same target or plan path is stable
- recent failure rate is acceptable
- scrubbing finds no sensitive values
- Quality Lab or operator review approves it

## Related Pages

- [Suggestions](./suggestions.md)
- [Search Tuning](../search/search-tuning.md)
