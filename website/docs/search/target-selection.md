---
title: Target Selection
description: Select a final tool from retrieved candidates while guarding weak LLM choices.
---

# Target Selection

Target selection chooses the final tool after retrieval. The selector can compare
the LLM's target with deterministic candidate evidence.

## Public API

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query=query,
    candidates=candidate_names,
    tools=tools,
    retrieval_results=retrieval_results,
    llm_target=llm_target,
)
```

## Output Fields

| Field | Meaning |
| --- | --- |
| `selected_target` | Final selected tool |
| `confidence` | Selector confidence |
| `overrode_llm` | Whether the LLM target was changed |
| `ambiguous` | Whether evidence margin was too weak |
| `reason_codes` | Stable diagnostic reasons |
| `rank_signals` | Evidence used for the decision |
| `candidate_evidence` | Per-candidate evidence summary |

## Policy

Default policy is strong-evidence first. Override only when deterministic
evidence is strong and the margin is sufficient. Otherwise keep the LLM target
and emit an ambiguity diagnostic.

## Related Pages

- [Tool Graph Search](./tool-graph-search.mdx)
- [Plan Synthesis](../plan/plan-synthesis.md)
