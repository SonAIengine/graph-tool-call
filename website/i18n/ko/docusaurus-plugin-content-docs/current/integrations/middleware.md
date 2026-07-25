---
title: Middleware
description: model invocation 전에 tool catalog를 필터링하는 middleware 패턴입니다.
---

# Middleware

Middleware integration은 model invocation 전에 tool catalog를 가로채고, 큰 raw
catalog를 compact graph-tool-call candidate set으로 바꿉니다.

agent stack 전체를 다시 만들 수는 없지만 LLM이 tool을 보기 전에 retrieval
layer를 넣을 수 있을 때 적합합니다.

가장 낮은 비용으로 붙일 수 있는 integration path입니다. host application의 실행 계층은
바꾸지 않고, model에 전달되는 tool list만 줄이고 설명 가능하게 만듭니다.

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

## OpenAI Client Patch

```python
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai, unpatch_openai

graph = ToolGraph()
graph.add_tools(openai_tools)

patch_openai(client, graph=graph, top_k=5, min_tools=10)

response = client.chat.completions.create(
    model="gpt-4o",
    tools=openai_tools,
    messages=[{"role": "user", "content": "delete a user account"}],
)

unpatch_openai(client)
```

`min_tools`는 작은 catalog에서 불필요하게 filtering하지 않도록 합니다.

## Anthropic Client Patch

```python
from graph_tool_call.middleware import patch_anthropic

patch_anthropic(client, graph=graph, top_k=5)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=anthropic_tools,
    messages=[{"role": "user", "content": "find customer orders"}],
)
```

middleware는 마지막 user message를 retrieval query로 사용합니다. "그거 취소해줘" 같은
multi-turn reference는 conversation state에서 compact search query를 만드는 상위 adapter가
더 적합합니다.

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

## Failure Mode

| 증상 | 가능 원인 | 보완 |
| --- | --- | --- |
| 모든 tool이 그대로 전달됨 | user message/tool 없음 또는 tool 수가 `min_tools`보다 작음 | request shape와 `min_tools` 확인 |
| candidate set이 틀림 | graph metadata 부족 또는 query context가 짧음 | evidence output 확인, alias/contract 보강 |
| patch가 두 번 적용됨 | client가 이미 patched 상태 | re-patch 전 `unpatch_*()` 호출 |
| 선택 tool 실행 실패 | middleware는 filtering만 담당 | host auth/request layer 점검 |

## 검증

```bash
poetry run pytest tests/test_middleware.py -q
```

## 관련 문서

- [Tool Graph 검색](../search/tool-graph-search.mdx)
- [Target 선택](../search/target-selection.md)
- [실패 분류](../plan/failure-taxonomy.md)
