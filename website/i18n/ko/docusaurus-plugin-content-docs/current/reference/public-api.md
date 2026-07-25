---
title: Public API
description: graph-tool-call adapter가 의존해도 되는 안정 import와 계약입니다.
---

# Public API

이 페이지는 application adapter가 의존해도 되는 public module과 entry point를
정리합니다. 여기에 있는 API는 XGEN 같은 제품 통합에서 버전이 올라가도
안정적으로 쓰기 위한 경계입니다.

문서에서 안정 계약이라고 명시하지 않은 internal helper import는 피하세요.

## Import 정책

| Import Path | 안정성 | 용도 |
| --- | --- | --- |
| `graph_tool_call` | stable | `ToolGraph`, `ToolSchema` 같은 core export |
| `graph_tool_call.graphify` | stable | OpenAPI collection artifact, retrieval, target selection, edge |
| `graph_tool_call.plan` | stable | Plan synthesis, plan schema, runner event |
| `graph_tool_call.learning` | stable | scrub된 trace learning record와 suggestion |
| `graph_tool_call.analyze` | stable | OpenAPI readiness와 graph diagnostic |
| `graph_tool_call.ingest.*` | 문서화된 경우만 | low-level ingest 구현 |
| `graph_tool_call.graphify.*` submodule | 문서화된 경우만 | public graphify export 뒤의 내부 구현 |

## Core 객체

```python
from graph_tool_call import ToolGraph, ToolSchema
```

`ToolGraph`는 작은 서비스나 로컬 실험에서 가장 편한 facade입니다. OpenAPI
ingest, retrieval, graph 분석, visualization export, OpenAPI tool execute를
한 객체에서 다룹니다.

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

tools = graph.retrieve("상태별 pet 조회", top_k=8)
ranked = graph.retrieve_with_scores("상태별 pet 조회", top_k=8)
report = graph.analyze()
```

`ToolSchema`는 ingest, graph build, retrieval, planning, adapter가 함께 쓰는
정규화된 tool representation입니다.

```python
from graph_tool_call import ToolSchema

tool = ToolSchema(
    name="getCustomerOrders",
    description="고객 주문을 조회합니다",
)
```

OpenAI, Anthropic, MCP tool definition이 이미 있다면 public parser를 쓰는 편이
좋습니다.

```python
from graph_tool_call import parse_tool

tool = parse_tool(
    {
        "name": "getCustomerOrders",
        "description": "고객 주문을 조회합니다",
        "parameters": {
            "type": "object",
            "required": ["customerId"],
            "properties": {"customerId": {"type": "string"}},
        },
    }
)
```

## Graphify API

대형 API collection을 저장하고 재사용하려면 graphify API를 사용하세요. 이
API는 product-neutral입니다. DB, cookie, user id, UI state, downstream auth
token을 알지 않습니다.

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    expand_candidates_with_producers,
    ingest_openapi_graphify,
    retrieve_graphify,
    select_target_candidate,
)
from graph_tool_call.graphify import (
    build_io_contract,
    derive_plan_trace_edges,
    extract_openapi_contract_index,
    merge_graph_edges,
    normalize_graph_edge,
)
```

### Collection artifact build

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

### 저장된 artifact 검색

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    query="환불 가능한 주문 목록",
    top_k=8,
    include_evidence=True,
)

for result in response["results"]:
    print(result["name"], result["score_breakdown"])
```

### LLM target guard

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="환불 가능한 주문 목록",
    candidates=[row["name"] for row in response["results"]],
    tools=graph.tools,
    retrieval_results=response["results"],
    llm_target="getOrderDetail",
)

print(selection["selected_target"])
print(selection["overrode_llm"])
print(selection["reason_codes"])
```

## Plan API

`plan` package는 transport-agnostic입니다. 엔진은 plan을 만들고 실행 흐름을
진행하지만, 실제 tool 호출 방식은 adapter가 결정합니다.

```python
from graph_tool_call.plan import (
    PathSynthesizer,
    Plan,
    PlanRunner,
    PlanStep,
    PlanSynthesisError,
    parse_intent,
    synthesize_failure_response,
    synthesize_success_response,
)
```

```python
from dataclasses import asdict

from graph_tool_call.plan import Plan, PlanRunner, PlanStep

plan = Plan(
    id="plan-1",
    goal="주문을 찾고 상세를 반환한다",
    steps=[
        PlanStep(id="s1", tool="searchOrders", args={"keyword": "A-100"}),
        PlanStep(id="s2", tool="getOrderDetail", args={"orderId": "${s1.items.0.id}"}),
    ],
)

def call_tool(name: str, args: dict):
    return executor.call(name, args)

runner = PlanRunner(call_tool)

for event in runner.run_stream(plan, trace_metadata={"collection_id": "orders"}):
    print(asdict(event))
```

## Learning API

Learning API는 이전 시도의 compact evidence를 저장합니다. LLM을 fine-tuning
하지 않고도 retrieval, selector, plan synthesis가 참고할 수 있는 근거를
축적하는 방식입니다.

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
)
```

## Adapter 경계

| Adapter 책임 | 이유 |
| --- | --- |
| DB read/write | 저장 구조와 tenancy는 제품마다 다름 |
| 사용자 인증 | 엔진은 live credential을 저장하면 안 됨 |
| session header와 cookie | runtime auth는 caller 책임 |
| SSE/UI forwarding | event transport는 제품별 구현 |
| 운영자 수동 보정 | 제품 metadata에 저장하고 옵션으로 전달 |

## 호환성 규칙

- public API는 기존 필드를 바꾸기보다 additive하게 확장합니다.
- collection graph artifact는 minor version 사이에서 계속 읽을 수 있어야 합니다.
- adapter는 rebuild 때 알 수 없는 필드를 보존해야 합니다.
- token, cookie, 사용자 식별값은 artifact, report, learning, event payload에
  저장하지 않습니다.

## 관련 문서

- [API Cheat Sheet](./api-cheat-sheet.md)
- [CLI](./cli.md)
- [Artifact Schema](./artifact-schemas.md)
- [Event Schema](./event-schemas.md)
- [Report Schema](./report-schemas.md)
- [Compatibility](./compatibility.md)
