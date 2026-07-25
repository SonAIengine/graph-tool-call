---
title: Trace Learning Loop
description: Improve search and planning from scrubbed execution traces without training the LLM.
---

# Trace Learning Loop

Trace learning improves retrieval, target selection, and planning from execution
history without fine-tuning the LLM.

The engine learns from evidence stored around a collection: successful targets,
plan paths, data-flow edges, and structured failure reasons. The LLM simply sees
better candidates and better metadata later.

## Mental Model

```text
run attempt
  -> scrub payload
  -> build learning record
  -> derive suggestions
  -> shadow compare
  -> promote after validation
  -> retrieval/selector sees low-weight evidence
```

## What Is Stored

Learning records store compact, scrubbed facts:

| Field | Purpose |
| --- | --- |
| `query` | Scrubbed user query |
| `query_family` | Normalized grouping key |
| `query_fingerprint` | Stable hash of the query family |
| `collection_id` | Collection-local scope |
| `attempt_id` | Attempt identifier |
| `session_id_hash` | Hashed session id, never raw session value |
| `selected_target` | Final selected tool |
| `llm_target` | LLM-proposed target, if available |
| `plan_tools` | Ordered successful or attempted plan tools |
| `failure_reason` | Stable failure reason, if any |
| `success` | Attempt status |
| `latency_ms` | End-to-end latency |
| `target_selector` | Scrubbed selector diagnostics |
| `trace_edges` | Scrubbed run-observed graph edge evidence |

Raw request/response bodies, tokens, cookies, API keys, and obvious personal
data are not stored.

## Why Not Train The LLM First?

Most early failures in large API collections are not model knowledge problems.
They are catalog evidence problems:

- the right tool is not high enough in Top-K
- sibling tools have weak action/resource/shape metadata
- required fields are not mapped to producers
- auth readiness is missing
- execution failure is not classified clearly

Trace learning fixes these by improving the graph evidence that the LLM sees.

## Suggestion Flow

```python
from graph_tool_call.learning import (
    build_trace_learning_record,
    derive_learning_suggestions,
)

record = build_trace_learning_record(
    query=query,
    collection_id=collection_id,
    selected_target=selected_target,
    plan_tools=plan_tools,
    success=True,
)

suggestions = derive_learning_suggestions(record, history=attempts)
```

## Adapter Boundary

graph-tool-call defines record and suggestion contracts. The product adapter
stores them, decides promotion policy, and keeps auth/user/session details out
of the engine.

## Related Pages

- [Scrubbing](../learning/scrubbing.md)
- [Suggestions](../learning/suggestions.md)
- [Shadow And Promotion](../learning/shadow-promotion.md)
- [Evidence Output](../search/evidence-output.md)
