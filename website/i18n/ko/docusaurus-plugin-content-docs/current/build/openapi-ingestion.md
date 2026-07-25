---
title: OpenAPI Ingestion
description: Swagger 또는 OpenAPI source를 graph-tool-call tool schema로 정규화합니다.
---

# OpenAPI Ingestion

OpenAPI ingestion은 Swagger 2.0 또는 OpenAPI 3.x source를 정규화된
`ToolSchema`로 바꿉니다. 각 operation은 method, path, operation id, summary,
parameter, schema, security hint, source metadata를 가진 tool 후보가 됩니다.

## 언제 사용하나

REST API specification에서 tool catalog를 만들 때 사용합니다. Swagger UI URL과
직접 JSON/YAML spec URL을 모두 대상으로 둘 수 있습니다.

product-specific auth token, cookie, database id, UI state는 엔진에 넣지 말고
adapter에 보관한 뒤 실행 시점에만 붙입니다.

## 최소 예제

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://example.com/swagger-ui/index.html")
tools = graph.retrieve("고객 주문 조회", top_k=8)
```

## Direct Graphify Entry Point

```python
from graph_tool_call.graphify import ingest_openapi_graphify

artifact = ingest_openapi_graphify("openapi.json")
print(artifact["metadata"]["tool_count"])
```

## Stable Metadata

| Field | Purpose |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | operation path |
| `metadata.openapi.operation_id` | stable operation identifier |
| `metadata.openapi.parameters` | query, path, header, cookie parameter |
| `metadata.api_contract` | consumes, produces, links |
| `metadata.ai_metadata` | deterministic semantic action/resource/module |

## 관련 문서

- [IO Contracts](./io-contracts.md)
- [Semantic Build](./semantic-build.md)
- [Readiness Diagnostics](./readiness-diagnostics.md)
