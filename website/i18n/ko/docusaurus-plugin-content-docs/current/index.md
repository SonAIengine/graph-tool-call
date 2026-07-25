# graph-tool-call

`graph-tool-call`은 LLM 에이전트를 위한 그래프 기반 도구 검색 엔진입니다.
OpenAPI spec, MCP tool, Python 함수를 searchable tool graph로 만들고, 에이전트가
필요로 하는 작은 후보 집합과 workflow 근거를 반환합니다.

## 왜 필요한가

대형 tool catalog에서는 두 가지 문제가 생깁니다.

- tool 정의가 너무 많아 모델 context를 넘칩니다.
- 유사도 검색은 tool 하나는 찾지만, 그 tool이 속한 workflow를 놓칩니다.

`graph-tool-call`은 keyword search, graph expansion, OpenAPI contract,
semantic metadata, target selection, trace evidence를 함께 사용해 이 문제를 줄입니다.

## 만들 수 있는 것

- 수천 개 tool을 LLM에 모두 넣지 않고 검색합니다.
- OpenAPI collection을 실행 가능한 tool graph로 변환합니다.
- LLM 호출 전에 deterministic evidence로 target 후보를 정렬합니다.
- 검색, plan, 실행 품질을 재현 가능한 gate로 검증합니다.
- 성공/실패 실행 trace를 다음 ranking의 evidence로 축적합니다.

## 먼저 볼 문서

- 첫 retrieval 흐름: [빠른 시작](getting-started/quickstart.md)
- 엔진 동작 방식: [Mental Model](getting-started/mental-model.md)
- 핵심 매뉴얼 페이지: [Tool Graph Search](search/tool-graph-search.mdx)
- Swagger/OpenAPI 빌드: [OpenAPI Ingestion](build/openapi-ingestion.md)
- 최종 tool 선택: [Target Selection](search/target-selection.md)
- 품질 확인: [Quality Lab](validation/quality-lab.md)
- API 확인: [Public API](reference/public-api.md)

## Manual Map

| Section | Use It For |
| --- | --- |
| [Build Tool Catalogs](build/openapi-ingestion.md) | OpenAPI, MCP, Python ingestion, semantic build, IO contract, readiness |
| [Search And Selection](search/tool-graph-search.mdx) | retrieval, evidence, candidate expansion, target selector, Korean search |
| [Plan And Execute](plan/plan-synthesis.md) | plan synthesis, user slot, runner event, failure taxonomy |
| [Learning Loop](concepts/trace-learning.md) | scrubbed trace, suggestion, shadow mode, promotion policy |
| [Validation](validation/benchmarks.md) | benchmark gate, Quality Lab, release gate |
| [Integrations](guides/xgen-integration.md) | XGEN, MCP, LangChain, middleware, direct API adapter |
| [Reference](reference/public-api.md) | public import, CLI, event, report, artifact, compatibility |

## 최소 예제

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

for tool in graph.retrieve("find pets by status", top_k=5):
    print(tool.name, tool.description)
```

## 현재 중점

현재 roadmap은 대형 enterprise API collection에 맞춰져 있습니다.

- deterministic OpenAPI contract 추출
- semantic action/resource/module 분류
- LLM target 선택을 보정하는 selector guard
- auth readiness 진단
- 성공/실패 실행 trace 기반 learning loop

public quality claim은 committed fixture, reproducible command, stored result
artifact 중 하나와 연결되어야 합니다.
