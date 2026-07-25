---
title: Direct API
description: framework adapter 없이 application code에서 graph-tool-call을 직접 호출합니다.
---

# Direct API

Direct API는 ingest, retrieval, target selection, planning, execution을
application code에서 직접 통제하고 싶을 때 사용합니다. 이미 auth, DB,
logging, HTTP execution을 갖고 있는 backend service에 가장 자연스러운
통합 방식입니다.

## 최소 retrieval

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
candidates = graph.retrieve_with_scores("고객 주문 조회", top_k=8)

for item in candidates:
    print(item.tool.name, item.score, item.confidence)
```

`ToolGraph`는 local tool, 작은 service, demo, test에 적합합니다.

## Artifact 기반 retrieval

대형 제품은 collection artifact를 한 번 build하고 여러 번 검색하는 방식이
좋습니다.

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    retrieve_graphify,
)

artifact = build_openapi_collection_artifact("openapi.json")

response = retrieve_graphify(
    artifact,
    query="환불 가능한 주문 목록",
    top_k=8,
    include_evidence=True,
)
```

artifact는 application storage에 저장하고 rebuild 때 unknown field를
보존하세요.

## Target selection

LLM이 target을 반환하면 deterministic evidence로 한 번 guard합니다.

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query=user_query,
    candidates=[row["name"] for row in response["results"]],
    tools=artifact["tools"],
    retrieval_results=response["results"],
    llm_target=llm_target,
)

target = selection["selected_target"]
```

`overrode_llm`, `ambiguous`, `reason_codes`는 log나 UI diagnostic에 그대로
남기면 좋습니다.

## Plan and execute

plan runner는 caller가 제공한 function을 호출합니다. auth, base URL, retry,
downstream HTTP behavior는 그 function 안에서 adapter가 처리합니다.

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

def call_tool(tool_name: str, args: dict):
    return api_executor.execute(tool_name, args, user_context=current_user)

runner = PlanRunner(call_tool)

for event in runner.run_stream(plan, trace_metadata={"request_id": request_id}):
    logger.info("plan_event", extra=asdict(event))
```

## Adapter checklist

| Concern | 권장 책임 |
| --- | --- |
| OpenAPI parsing과 graph artifact | graph-tool-call |
| search, evidence, selector signal | graph-tool-call |
| DB table shape | application |
| auth profile과 session header | application |
| tool execution과 mutation safety | application |
| SSE/UI forwarding | application |
| Quality Lab case storage | application |
| trace learning suggestion | graph-tool-call schema, application storage |

## 관련 문서

- [Public API](../reference/public-api.md)
- [Artifact Schema](../reference/artifact-schemas.md)
- [Tool Graph 검색](../search/tool-graph-search.mdx)
- [Plan 합성](../plan/plan-synthesis.md)
