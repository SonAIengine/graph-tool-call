---
title: LangChain
description: LangChain tool adapter 앞에서 graph-tool-call retrieval을 사용합니다.
---

# LangChain

graph-tool-call은 LangChain tool set을 model에 전달하기 전에 retrieval과
filtering layer로 사용할 수 있습니다. 목표는 LLM이 보는 tool catalog를 작게
유지하면서, 각 candidate가 포함된 이유를 evidence로 남기는 것입니다.

## 기본 pattern

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_functions(langchain_tools)

def tools_for_query(query: str):
    candidates = graph.retrieve(query, top_k=8)
    names = {candidate.name for candidate in candidates}
    return [tool for tool in langchain_tools if tool.name in names]
```

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

## 관련 문서

- [Tool Graph 검색](../search/tool-graph-search.mdx)
- [Target 선택](../search/target-selection.md)
- [Public API](../reference/public-api.md)
