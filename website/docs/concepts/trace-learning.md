---
title: Trace Learning Loop
description: Improve search, target selection, and planning from scrubbed execution traces without training the LLM.
---

# Trace Learning Loop

Trace learning improves retrieval, target selection, and planning from execution
history without fine-tuning the LLM.

The first goal is not to train a model. The first goal is to capture safe,
collection-scoped evidence from real runs, compare it in shadow mode, and promote
only the evidence that repeatedly improves future search and plan behavior.

## Mental Model

```text
run attempt
  -> scrub payload
  -> build learning record
  -> derive suggestions
  -> keep suggestions in shadow
  -> validate with repeated success or Quality Lab
  -> promote
  -> retrieval and target selector receive low-weight evidence
```

The LLM sees better candidates and metadata later. The LLM itself is not changed
by this loop.

## Why This Comes Before Fine-Tuning

Most early failures in large API collections are evidence problems:

- the correct tool is not high enough in Top-K
- sibling tools have weak action, resource, or result-shape metadata
- the selector cannot explain why a target is preferred
- required fields are not linked to producers
- auth failures are not separated from request or API failures
- successful retries are not fed back into search or plan evidence

Trace learning fixes these by improving the graph and selector signals that the
LLM receives. Fine-tuning can come later, after there is clean evidence worth
training on.

## Public API

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
    summarize_learning_state,
)
```

The API is deliberately storage-neutral. graph-tool-call creates records,
suggestions, summaries, and optional ranking signals. Your adapter decides where
to persist them and when to promote them.

## Learning Record

Use `build_trace_learning_record()` after a search, plan, or execute attempt.

```python
record = build_trace_learning_record(
    query="show order detail",
    collection_id="orders-api",
    attempt_id="attempt_001",
    session_id="runtime-session-id",
    selected_target="getOrderDetail",
    llm_target="getOrderInfo",
    plan_tools=["findOrder", "getOrderDetail"],
    failure_reason=None,
    success=True,
    latency_ms=842,
    target_selector={
        "selected_target": "getOrderDetail",
        "overrode_llm": True,
        "reason_codes": ["llm_target_overridden"],
    },
    trace_edges=[
        {
            "source": "findOrder",
            "target": "getOrderDetail",
            "data_flow": {"to_field": "orderNo"},
        }
    ],
)
```

The returned record is JSON-safe and compact.

| Field | Purpose |
| --- | --- |
| `query` | Scrubbed user query |
| `query_family` | Normalized grouping key for similar queries |
| `query_fingerprint` | Stable hash of the query family |
| `collection_id` | Collection-local scope |
| `attempt_id` | Attempt identifier |
| `session_id_hash` | Hashed session id, never the raw value |
| `selected_target` | Final selected tool |
| `llm_target` | LLM-proposed target, if available |
| `plan_tools` | Ordered successful or attempted plan tools |
| `failure_reason` | Stable reason code, if any |
| `success` | Attempt status |
| `latency_ms` | End-to-end latency |
| `target_selector` | Scrubbed selector diagnostics |
| `trace_edges` | Scrubbed run-observed graph edge evidence |
| `created_at` | ISO timestamp |

Raw request bodies, raw response bodies, tokens, cookies, API keys, and obvious
personal data are not stored.

## Scrubbing Boundary

Every record field is passed through `scrub_trace_payload()`.

```python
clean = scrub_trace_payload(
    {
        "Authorization": "Bearer secret-token",
        "email": "person@example.com",
        "response_body": {"orderNo": "1234"},
    }
)
```

Example output:

```json
{
  "Authorization": "[REDACTED]",
  "email": "[REDACTED_EMAIL]",
  "response_body": "[REDACTED]"
}
```

Scrubbing is a safety boundary, not a data science transformation. If a payload
cannot be safely compacted, reject the learning record.

## Suggestion Types

`derive_learning_suggestions()` converts a successful record into candidate
improvements.

| Suggestion Type | Meaning | Typical Consumer |
| --- | --- | --- |
| `target_preference` | This query family repeatedly selected this target | retrieval and target selector |
| `plan_path` | This ordered plan path worked | plan synthesis |
| `data_flow_edge` | A runtime trace showed field flow between tools | graph expansion and planner |
| `field_mapping` | A field mapping candidate should be reviewed | adapter or operator UI |
| `context_default_candidate` | A context default may remove user-input prompts | adapter settings |
| `enum_mapping_candidate` | An enum label/value mapping may be useful | adapter settings |

Only the first three are derived directly from the current helper. The other
types are part of the public suggestion vocabulary so adapters can add reviewed
signals without changing the contract.

## Suggestion Lifecycle

```text
suggested
  -> promotable
  -> promoted
  -> used as low-weight retrieval/selector evidence

suggested
  -> rejected
  -> ignored by retrieval/selector
```

The default promotion policy is conservative:

| Policy Field | Default | Meaning |
| --- | --- | --- |
| `min_success_observations` | `2` | repeated success required before a suggestion becomes promotable |
| `max_recent_failure_ratio` | `0.5` | avoid promoting evidence from unstable query families |
| `max_attempts` | `50` | compact storage bound for recent attempts |
| `max_suggestions` | `100` | compact storage bound for suggestions |

Adapters can require a human approval step before changing `promotable` to
`promoted`.

## Derive Suggestions

```python
from graph_tool_call.learning import derive_learning_suggestions

suggestions = derive_learning_suggestions(
    record,
    history=previous_attempts,
    existing_suggestions=current_suggestions,
    promotion_policy={"min_success_observations": 2},
)
```

Store returned suggestions under the collection, not globally. A target
preference learned from one API collection should not leak into another
collection.

## Apply Learning Signals

Learning boosts are optional and low-weight.

```python
from graph_tool_call.learning import apply_learning_suggestions

ranked = apply_learning_suggestions(
    "show order detail",
    candidates=[
        {"name": "getOrderInfo", "score": 0.41},
        {"name": "getOrderDetail", "score": 0.39},
    ],
    suggestions=collection_learning["suggestions"],
    mode="promoted",
)
```

Example signal:

```json
{
  "source": "learning",
  "target": "getOrderDetail",
  "suggestion_type": "target_preference",
  "status": "promoted",
  "observations": 3,
  "score": 0.045
}
```

In `mode="promoted"`, only promoted suggestions affect ranking. Shadow analysis
can use `mode="shadow"` to compare suggested and promotable evidence without
changing production behavior.

## Collection Storage Shape

A product adapter can store learning under a collection graph artifact.

```json
{
  "learning": {
    "attempts": [],
    "suggestions": [],
    "promotion_policy": {
      "min_success_observations": 2,
      "max_recent_failure_ratio": 0.5
    },
    "summary": {
      "attempt_count": 0,
      "success_rate": null,
      "promoted_count": 0
    }
  }
}
```

Use `summarize_learning_state()` to build a small UI/API summary.

## Observe, Shadow, Promote

| Mode | What Happens | Production Ranking Changes? |
| --- | --- | --- |
| observe | attempts and suggestions are recorded | no |
| shadow | learning-applied result is computed for comparison | no |
| promoted | promoted suggestions add low-weight signals | yes |

This prevents one lucky success from strongly changing future behavior.

## Quality Lab Integration

Quality Lab should record both the original result and the learning-shadowed
result.

| Metric | Meaning |
| --- | --- |
| `learning_suggestions_created` | suggestions derived from the run |
| `learning_applied_shadow_rank` | rank after applying shadow suggestions |
| `promotion_status` | `suggested`, `promotable`, `promoted`, or `rejected` |
| `target_rank_delta` | whether learning would move the expected target upward |

Promote only after Quality Lab or repeated real runs prove improvement.

## Adapter Boundary

graph-tool-call defines record and suggestion contracts. Product adapters own:

- persistence
- retention policy
- operator approval
- collection-level isolation
- auth/session resolution
- UI controls for promote/reject
- deciding whether shadow or promoted mode is active

The engine must not receive raw credentials or user identifiers.

## Troubleshooting

| Symptom | Check | Likely Fix |
| --- | --- | --- |
| suggestions are never created | record `success` and `selected_target` | ensure successful runs build learning records |
| suggestions never become promotable | matching query fingerprint and success count | inspect query normalization and history retention |
| learning changes ranking too aggressively | `mode`, `max_boost`, suggestion status | use `promoted` mode only and lower boost |
| sensitive strings appear in learning JSON | `scrub_trace_payload` tests | reject record and add scrub rule |
| target improves in shadow but not production | promotion status | approve or promote after gate passes |

## Validation

```bash
poetry run pytest tests/test_trace_learning.py -q
poetry run pytest tests/ -q -k "learning or quality_lab or target_selector"
```

For documentation-only changes:

```bash
cd website
npm run typecheck
npm run build
```

## Related Pages

- [Scrubbing](../learning/scrubbing.md)
- [Suggestions](../learning/suggestions.md)
- [Shadow And Promotion](../learning/shadow-promotion.md)
- [Target Selection](../search/target-selection.md)
- [Evidence Output](../search/evidence-output.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
