---
title: Target Selection
description: retrieved candidate에서 최종 tool을 선택하고 약한 LLM 선택을 guard합니다.
---

# Target Selection

Target selection은 retrieval 이후 최종 tool을 고릅니다. selector는 LLM target과
deterministic candidate evidence를 비교할 수 있습니다.

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
| `selected_target` | 최종 선택된 tool |
| `confidence` | selector confidence |
| `overrode_llm` | LLM target이 바뀌었는지 |
| `ambiguous` | evidence margin이 약했는지 |
| `reason_codes` | stable diagnostic reasons |
| `rank_signals` | decision에 사용된 evidence |
| `candidate_evidence` | candidate별 evidence summary |

## Policy

기본 정책은 strong-evidence first입니다. deterministic evidence가 강하고 margin이
충분할 때만 override합니다. 그렇지 않으면 LLM target을 유지하고 ambiguity
diagnostic을 남깁니다.

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Plan Synthesis](../plan/plan-synthesis.md)
