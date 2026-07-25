---
title: API Cheat Sheet
description: graph-tool-call workflow마다 어떤 public API 또는 CLI command를 써야 하는지 고릅니다.
---

# API Cheat Sheet

해야 할 일은 아는데 어떤 public API를 써야 할지 헷갈릴 때 이 페이지를 사용합니다.
각 row는 안정 entry point, 기대 output, 자세한 manual page로 이어집니다.

## 선택 매트릭스

| 작업 | Public API 또는 CLI | Output | 다음 문서 |
| --- | --- | --- | --- |
| OpenAPI source 하나로 retrieval 시도 | `ToolGraph.from_url(...).retrieve_with_scores(...)` 또는 `graph-tool-call search` | ranked `RetrievalResult` row | [빠른 시작](../getting-started/quickstart.md) |
| 저장 가능한 collection artifact build | `build_openapi_collection_artifact(...)` 또는 `graph-tool-call build-openapi-collection` | tools, graph, readiness, semantics가 들어간 `collection.json` | [Collection Artifacts](../build/collection-artifacts.md) |
| build 전 OpenAPI source 점검 | `analyze_openapi_collection(...)` 또는 `graph-tool-call inspect-openapi` | `OpenAPICollectionReport` | [Readiness Diagnostics](../build/readiness-diagnostics.md) |
| operation contract 추출 | `extract_openapi_contract_index(...)` | schema와 security가 보존된 operation contract row | [IO Contracts](../build/io-contracts.md) |
| 저장된 artifact를 evidence와 함께 검색 | `ToolGraph.load(...)`와 `retrieve_graphify(...)` | `results`, `subgraph_text`, `intent`, `stats`가 있는 response object | [Tool Graph Search](../search/tool-graph-search.mdx) |
| 최종 target 선택 | `select_target_candidate(...)` | `selected_target`, confidence, reason code, candidate evidence | [Target Selection](../search/target-selection.md) |
| deterministic plan build | `PathSynthesizer(...).synthesize(...)` | step과 synthesis metadata가 있는 `Plan` | [Plan Synthesis](../plan/plan-synthesis.md) |
| 실행 event stream | `PlanRunner(...).run_stream(...)` | `asdict(event)`로 변환 가능한 typed runner event | [Runner Events](../plan/runner-events.md) |
| trace learning evidence 저장 | `build_trace_learning_record(...)`와 `derive_learning_suggestions(...)` | scrub된 attempt record와 suggestion | [Trace Learning](../concepts/trace-learning.md) |
| filtered MCP surface 제공 | `graph-tool-call serve` 또는 `graph-tool-call proxy` | MCP server/proxy endpoint | [MCP Server](../integrations/mcp-server.md) |

## 최소 OpenAPI Build

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"tenantId", "siteNo"},
    paging_field_names={"page", "size"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

service나 UI가 diagnostics, quality result, learning suggestion, operator manual
metadata를 저장해야 한다면 collection artifact를 사용합니다.

## 최소 Evidence Retrieval

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    "환불 가능한 주문 목록을 찾아줘",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["name"])
print(first["score_breakdown"])
print(first["semantic_evidence"])
print(response["stats"])
```

`response["results"]`는 selector-ready candidate set으로 봅니다.
`response["subgraph_text"]`는 downstream LLM에 넘길 compact context block으로 봅니다.

## 최소 Target Guard

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="환불 가능한 주문 목록을 찾아줘",
    candidates=[row["name"] for row in response["results"]],
    tools=graph.tools,
    retrieval_results=response["results"],
    llm_target="getOrderDetail",
)

print(selection["selected_target"])
print(selection["overrode_llm"])
print(selection["reason_codes"])
```

기본 selector policy는 보수적입니다. 약한 LLM 선택을 조용히 덮어쓰기보다 ambiguity를
명시적으로 기록합니다.

## 최소 Plan

```python
from graph_tool_call.plan import PathSynthesizer, PlanSynthesisError

graph_payload = {
    "graph": graph.graph.to_dict(),
    "tools": {name: tool.to_dict() for name, tool in graph.tools.items()},
}

try:
    plan = PathSynthesizer(
        graph_payload,
        context_defaults={"siteNo": "1001"},
    ).synthesize(
        target=selection["selected_target"],
        goal="환불 가능한 주문 목록을 찾아줘",
        entities={"keyword": "refund-ready"},
    )
except PlanSynthesisError as exc:
    print(exc.to_dict())
else:
    print(plan.id)
    print([step.tool for step in plan.steps])
    print(plan.metadata["synthesis"])
```

exception string을 파싱하지 말고 `exc.to_dict()`를 저장합니다.

## Adapter Boundary

graph-tool-call은 product-neutral하게 둡니다.

| graph-tool-call에 둘 것 | Adapter에 둘 것 |
| --- | --- |
| schema normalization과 contract extraction | source 저장과 tenant policy |
| retrieval, evidence, target selection | LLM provider/model routing |
| plan schema와 runner event contract | auth header, cookie, user id, SSE, UI |
| scrubbed trace-learning helper | 승인 workflow와 rollout policy |

## 품질 체크리스트

대형 catalog를 agent에 연결하기 전에 아래 질문에 답할 수 있어야 합니다.

- `inspect-openapi`가 `ready` 또는 이해한 `warning`을 반환했는가?
- retrieval이 기대 target을 Top-K gate 안에 반환하는가?
- `score_breakdown`에 action/resource/shape/contract evidence가 있는가?
- `select_target_candidate()`가 target을 선택하거나 ambiguity를 명시했는가?
- `PathSynthesizer`가 plan 또는 structured failure reason을 반환하는가?
- execute가 unsafe API call 전에 auth readiness로 차단되는가?

## 관련 문서

- [Public API](./public-api.md)
- [CLI](./cli.md)
- [Artifact Schemas](./artifact-schemas.md)
- [Quality Gates](../guides/quality-gates.md)
