---
title: LangChain
description: LangChain tool adapter 앞에서 graph-tool-call retrieval을 사용합니다.
---

# LangChain

graph-tool-call은 LangChain tool set을 model에 전달하기 전에 retrieval과
filtering layer로 사용할 수 있습니다. 목표는 LLM이 보는 tool catalog를 작게
유지하면서, 각 candidate가 포함된 이유를 evidence로 남기는 것입니다.

이미 LangChain tool을 가지고 있고 downstream tool implementation을 바꾸지 않은 채
query별 tool filtering을 넣고 싶을 때 사용합니다.

## 기본 pattern

```python
from graph_tool_call.langchain import filter_tools

filtered = filter_tools(langchain_tools, "cancel an order", top_k=8)
```

`filter_tools()`는 원본 tool object를 보존합니다. 반환된 object는 agent가 이미 호출할 수
있는 같은 LangChain tool입니다.

## Reusable Toolkit

graph를 한 번 만들고 여러 turn에서 재사용합니다.

```python
from graph_tool_call.langchain import GraphToolkit

toolkit = GraphToolkit(langchain_tools, top_k=8)

def tools_for_turn(user_query: str):
    return toolkit.get_tools(user_query)
```

`toolkit.graph`는 inspect, save, test reuse가 가능합니다.

## LangGraph Agent

LangGraph ReAct agent에서는 다음처럼 사용합니다.

```python
from graph_tool_call.langchain import create_agent

agent = create_agent(
    model,
    tools=langchain_tools,
    top_k=5,
    query_mode="message",
)
```

`query_mode="message"`는 마지막 user message를 retrieval query로 사용합니다. multi-turn
reference 때문에 generated search query가 필요할 때만 `query_mode="llm"`을 사용합니다.
이 모드는 turn마다 LLM call이 하나 추가됩니다.

## Gateway tools

agent framework가 작은 고정 tool set을 선호한다면 모든 downstream operation을
노출하는 대신 search gateway tool을 노출할 수 있습니다.

```python
from graph_tool_call import create_gateway_tools

gateway_tools = create_gateway_tools(
    graph,
    top_k=8,
)
```

model은 gateway에 검색을 요청하고, application은 선택된 downstream tool을
자체 policy에 따라 표시하거나 실행합니다.

## Pattern 선택

| Pattern | 사용 시점 | Tradeoff |
| --- | --- | --- |
| `filter_tools()` | agent call 전 one-shot filtering | graph 미제공 시 rebuild |
| `GraphToolkit` | 같은 catalog를 여러 turn에서 재사용 | 단순하고 명시적 |
| `create_agent()` | LangGraph ReAct flow에서 turn별 filtering | framework-specific |
| gateway tools | model이 search를 명시적으로 호출해야 함 | tool-call step이 하나 늘어남 |

## 권장 control

| Control | 이유 |
| --- | --- |
| `top_k` | LLM에 보이는 tool count 제한 |
| score evidence | candidate 노출 이유 설명 |
| target selector guard | 명백한 LLM target mismatch 방지 |
| Quality Lab case | catalog 확대 전 regression 검출 |
| host-side execution | auth와 side effect를 application이 통제 |

## 흔한 실수

- retrieval 후에도 모든 LangChain tool을 model에 전달함
- score/evidence metadata를 버려서 실패 분석이 어려움
- engine이 runtime credential을 갖게 만듦
- search hit를 plan/execute readiness의 증거로 착각함

## 검증

```bash
poetry run pytest tests/test_langchain_toolkit.py tests/test_langchain_agent.py -q
```

## 관련 문서

- [Tool Graph 검색](../search/tool-graph-search.mdx)
- [Target 선택](../search/target-selection.md)
- [Public API](../reference/public-api.md)
