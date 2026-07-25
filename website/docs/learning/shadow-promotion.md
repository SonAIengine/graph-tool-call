---
title: Shadow And Promotion
description: Apply trace learning safely through observe, shadow, and promote stages.
---

# Shadow And Promotion

The default learning policy is:

```text
observe -> shadow -> promote
```

A successful trace is evidence, not an immediate production rule. Shadow and
promotion prevent the system from overfitting to a single lucky run, stale auth
context, or a one-off API state.

## Modes

| Mode | Behavior | Ranking Impact | Recommended Use |
| --- | --- | --- | --- |
| `observe` | Store scrubbed attempts and suggestions | none | first enablement on a collection |
| `shadow` | Compute learning-applied ranking beside current ranking | none on execution | dev and early production rollout |
| `promoted` | Apply validated low-weight signals | small additive boost | validated collections only |

The mode can be global, collection-level, or Quality Lab-specific. Collection
level is the safest default because evidence from one collection should not
affect another.

## Observe Mode

Observe mode records attempts and suggestions. It does not change behavior.

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
    merge_learning_suggestions,
)

record = build_trace_learning_record(
    query=query,
    collection_id=collection_id,
    selected_target=selected_target,
    plan_tools=plan_tools,
    success=success,
    failure_reason=failure_reason,
)

new_suggestions = derive_learning_suggestions(record, history=attempts)
suggestions = merge_learning_suggestions(
    existing=suggestions,
    incoming=new_suggestions,
    history=[*attempts, record],
)
```

Use observe mode until you can prove that records are scrubbed and suggestions
are collection-scoped.

## Shadow Mode

Shadow mode computes what would have happened if learning were active, but keeps
the actual selected target and executed plan unchanged.

```python
from graph_tool_call.learning import apply_learning_suggestions

shadow = apply_learning_suggestions(
    query=query,
    candidates=current_candidates,
    suggestions=collection_suggestions,
    mode="shadow",
)
```

Store both current and shadow results.

| Field | Meaning |
| --- | --- |
| `current_selected_target` | target used by the live path |
| `shadow_selected_target` | target that learning would prefer |
| `current_rank` | expected target rank before learning |
| `shadow_rank` | expected target rank with learning |
| `rank_delta` | positive when learning moves the expected target up |
| `selected_target_changed` | whether learning would alter execution behavior |
| `failure_reason_changed` | whether learning would avoid a known failure |

Shadow mode is useful even when execution cannot run because of auth readiness.
Search and target selection can still be compared safely.

## Promotion Gate

A suggestion should become `promotable` only when the evidence is repeated and
clean.

| Gate | Requirement |
| --- | --- |
| repeated success | same query family succeeds at least twice by default |
| stable target | selected target or plan path remains consistent |
| acceptable failure ratio | recent matching failures stay below policy |
| scrubbed evidence | no raw credential, raw body, or personal data |
| collection isolation | suggestion belongs to the same collection |
| validation | Quality Lab, operator review, or rollout policy approves it |

The default helper policy uses:

```json
{
  "min_success_observations": 2,
  "max_recent_failure_ratio": 0.5,
  "max_attempts": 50,
  "max_suggestions": 100
}
```

Adapters can be stricter. For write-capable collections, require explicit
operator approval before `promoted`.

## Promotion Flow

```text
suggested
  -> promotable
  -> operator or policy approves
  -> promoted
  -> retrieval/selector sees low-weight signal
```

Promotion should update only the suggestion status and metadata. It should not
rewrite the original attempt record.

Example promoted suggestion:

```json
{
  "id": "target_preference:3f9d6dd00a0e50c1",
  "type": "target_preference",
  "target": "getRefundableOrders",
  "status": "promoted",
  "observations": 3,
  "promoted_by": "quality_lab",
  "promoted_at": "2026-07-25T08:00:00Z",
  "promotion_reason": "top1 improved in 3 repeated cases"
}
```

## Rejection Flow

Rejected suggestions should remain visible. They explain why a tempting pattern
was not applied.

| Rejection Reason | Meaning |
| --- | --- |
| `sensitive_evidence` | scrubbing found unsafe data |
| `unstable_target` | repeated runs selected different targets |
| `weak_shadow_delta` | shadow ranking did not improve enough |
| `operator_rejected` | human rejected the suggestion |
| `collection_policy_blocked` | collection does not allow learning promotion |

Rejected suggestions should not be passed into promoted-mode ranking.

## Ranking Impact

Learning signals must remain small and explainable.

| Signal | Intended Effect |
| --- | --- |
| `target_preference` | nudge a close target upward for the same query family |
| `plan_path` | prefer a previously successful path when planner choices tie |
| `data_flow_edge` | make a proven producer/consumer edge visible to planning |

Do not let learning override exact action/resource/contract evidence. If the
learning signal would reverse a strong deterministic signal, keep it shadowed
and require review.

## Rollout Strategy

1. Start with `observe` on one collection.
2. Confirm records are scrubbed and bounded.
3. Enable `shadow` in Quality Lab.
4. Track rank deltas and target changes.
5. Promote only suggestions with repeated success.
6. Enable `promoted` mode for low-risk read flows.
7. Add write flows only with cleanup assertions and operator review.

## Quality Lab Assertions

Quality Lab should verify learning separately from base search quality.

```json
{
  "learning": {
    "mode": "shadow",
    "expected_target": "getRefundableOrders",
    "assertions": {
      "shadow_rank_lte_current_rank": true,
      "selected_target_changed": false,
      "raw_secret_present": false,
      "promotion_status": ["suggested", "promotable"]
    }
  }
}
```

This keeps learning evidence visible without claiming that production ranking
has changed.

## UI Checklist

| UI Element | Purpose |
| --- | --- |
| mode badge | distinguish observe, shadow, and promoted |
| suggestion status | show whether ranking is affected |
| current vs shadow rank | show measured improvement |
| evidence preview | expose scrubbed evidence |
| promote/reject controls | let operators govern risky changes |
| rejection reason | prevent repeated review of bad suggestions |
| collection scope | show that evidence does not cross collections |

## Failure Handling

Failures should remain part of the learning state.

- repeated failures should block promotion
- auth readiness failures should not teach target preference by themselves
- HTTP failures should be classified before deriving planning evidence
- cleanup failures should block write-case promotion
- uncaught server errors should never become learning evidence

Learning from failures is useful, but failure records should mostly constrain
promotion rather than boost future ranking.

## Troubleshooting

| Symptom | Check | Likely Fix |
| --- | --- | --- |
| one success immediately changes ranking | active mode and suggestion status | keep new suggestions in observe/shadow |
| shadow target changes too often | `ambiguous_target`, rank margin | require operator review |
| promoted suggestion never applies | query fingerprint and collection id | verify same query family and same collection |
| write case gets promoted | mutation safety and cleanup assertions | block promotion until cleanup passes |
| operators cannot tell why promoted | promotion metadata | store `promoted_by`, `promoted_at`, and reason |

## Validation

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/ -q -k "learning or quality_lab"
```

For documentation-only changes:

```bash
cd website
npm run typecheck
npm run build
```

## Related Pages

- [Trace Learning Loop](../concepts/trace-learning.md)
- [Suggestions](./suggestions.md)
- [Scrubbing](./scrubbing.md)
- [Quality Lab](../validation/quality-lab.md)
- [Search Tuning](../search/search-tuning.md)
