---
title: 문서
description: 대형 LLM tool catalog를 searchable tool graph로 만드는 방법을 시작합니다.
---

# graph-tool-call 문서

`graph-tool-call`은 LLM agent를 위한 graph-structured tool retrieval engine입니다.
OpenAPI spec, MCP tool, Python 함수를 searchable tool graph로 만들고, compact
candidate, execution contract, target-selection evidence, quality diagnostic을
반환합니다.

agent가 모델 context에 안전하게 넣기 어려울 만큼 많은 tool을 갖고 있거나, 올바른
tool 선택이 request field, response field, workflow order, auth readiness, 과거 실행
근거에 달려 있다면 이 매뉴얼을 사용하세요.

## 경로 선택

| 목표 | 시작 문서 | 완료되면 얻는 것 |
| --- | --- | --- |
| 로컬에서 먼저 실행 | [빠른 시작](getting-started/quickstart.md) | 첫 OpenAPI 검색, graph build, readiness check |
| 아키텍처 이해 | [Mental Model](getting-started/mental-model.md) | ingest -> contract -> retrieve -> select -> plan -> learn 모델 |
| Swagger/OpenAPI 빌드 | [OpenAPI Ingestion](build/openapi-ingestion.md) | contract와 semantic metadata가 들어간 collection artifact |
| 대형 catalog 검색 | [Tool Graph Search](search/tool-graph-search.mdx) | score/evidence가 포함된 ranked candidate |
| LLM target 선택 guard | [Target Selection](search/target-selection.md) | `llm_target` 주변 deterministic selector diagnostic |
| multi-tool workflow 실행 | [Plan Synthesis](plan/plan-synthesis.md) | plan, user input slot, runner event, failure reason |
| 품질 검증 | [Quality Lab](validation/quality-lab.md) | search, plan, execute, benchmark gate |
| application 연결 | [XGEN Integration](guides/xgen-integration.md) | DB, auth, UI, SSE, execution을 소유하는 product adapter |

## 최소 retrieval

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
results = graph.retrieve_with_scores("find pets by status", top_k=3)

for row in results:
    print(row.tool.name, row.score)
```

디버깅할 때는 모든 tool schema를 LLM에 보내기보다 evidence object를 요청합니다.

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph,
    "find pets by status",
    top_k=3,
    include_evidence=True,
)

first = response["results"][0]
print(first["score_breakdown"])
```

## 핵심 workflow

| Workflow | Manual | 주요 artifact |
| --- | --- | --- |
| Catalog build | [Build Tool Catalogs](build/openapi-ingestion.md) | `ToolSchema`, `api_contract`, `semantic_summary`, readiness report |
| Search and select | [Search And Selection](search/tool-graph-search.mdx) | retrieval row, score breakdown, `target_selector` |
| Plan and execute | [Plan And Execute](plan/plan-synthesis.md) | `Plan`, `PlanStep`, `user_input_slots`, runner event |
| Trace learning | [Learning Loop](concepts/trace-learning.md) | scrubbed attempt, suggestion, shadow/promotion state |
| Claim validation | [Validation](validation/benchmarks.md) | benchmark artifact, Quality Lab result, release gate |
| Client integration | [Integrations](guides/xgen-integration.md) | XGEN adapter, MCP gateway, LangChain tool, middleware patch |
| Contract lookup | [Reference](reference/public-api.md) | public import, CLI, event schema, report schema |

## Engine이 책임지는 것

라이브러리는 product-neutral이어야 합니다. deterministic graph/search/plan logic과
inspect/test 가능한 artifact를 책임집니다.

| Engine 책임 | Product adapter 책임 |
| --- | --- |
| OpenAPI/MCP/Python ingest | source 저장과 tenant policy |
| request/response contract extraction | user/session auth resolution |
| retrieval과 score evidence | model/provider routing |
| target selector diagnostic | UI 결정과 사용자 confirmation |
| plan synthesis와 runner event schema | 실제 HTTP 실행과 audit logging |
| trace-learning suggestion | 승인, 거절, rollout policy |

## 품질 기준

좋은 tool retrieval 작업은 재현 가능해야 합니다. public quality claim을 내거나 큰
collection을 운영에 붙이기 전에는 아래가 있어야 합니다.

- committed fixture 또는 named live collection
- deterministic search/selector metric
- execute를 claim한다면 plan/execute gate
- LLM 기반 결과라면 model/provider 정보
- raw result artifact 또는 Quality Lab record
- synthetic, shadow-mode, read-only benchmark 여부 명시

## Manual Map

| Section | Use It For |
| --- | --- |
| [Getting Started](getting-started/quickstart.md) | installation, quickstart, mental model |
| [Build Tool Catalogs](build/openapi-ingestion.md) | OpenAPI, MCP, Python ingestion, semantic build, IO contract, readiness |
| [Search And Selection](search/tool-graph-search.mdx) | retrieval, evidence, candidate expansion, target selector, Korean search |
| [Plan And Execute](plan/plan-synthesis.md) | plan synthesis, user slot, runner event, failure taxonomy |
| [Learning Loop](concepts/trace-learning.md) | scrubbed trace, suggestion, shadow mode, promotion policy |
| [Validation](validation/benchmarks.md) | benchmark gate, Quality Lab, release gate |
| [Integrations](guides/xgen-integration.md) | XGEN, MCP, LangChain, middleware, direct API adapter |
| [Reference](reference/public-api.md) | public import, CLI, event, report, artifact, compatibility |
