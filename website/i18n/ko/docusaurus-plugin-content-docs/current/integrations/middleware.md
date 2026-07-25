---
title: Middleware
description: model invocation 전에 tool catalog를 필터링하는 middleware 패턴입니다.
---

# Middleware

Middleware integration은 model invocation 전에 tool catalog를 가로채고, 큰 raw
catalog를 compact graph-tool-call candidate set으로 바꿉니다.

agent stack 전체를 다시 만들 수는 없지만 LLM이 tool을 보기 전에 retrieval
layer를 넣을 수 있을 때 적합합니다.

## Flow

1. application이 전체 tool catalog를 준비합니다.
2. middleware가 `ToolGraph`를 build 또는 load합니다.
3. user query를 graph에서 검색합니다.
4. top candidate와 evidence만 LLM에 전달합니다.
5. 최종 tool execution은 host application이 그대로 수행합니다.

## 최소 pattern

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_functions(all_tools)

def before_model_call(user_query: str, full_tools: list):
    candidates = graph.retrieve(user_query, top_k=8)
    return [tool_registry[item.name] for item in candidates]
```

## Adapter boundary

| Middleware가 하는 일 | Host application이 하는 일 |
| --- | --- |
| candidate retrieval | user authentication |
| score evidence 보존 | tool execution |
| tool count 제한 | business policy enforcement |
| ambiguous selection 진단 | audit log 저장 |

## 보존하면 좋은 diagnostic

- query
- candidate name
- score breakdown
- selected target
- selector reason code
- token/context reduction
- execution failure reason

credential이나 sensitive output 원문은 log로 남기지 않습니다.

## 관련 문서

- [Tool Graph 검색](../search/tool-graph-search.mdx)
- [Target 선택](../search/target-selection.md)
- [실패 분류](../plan/failure-taxonomy.md)
