---
title: OpenAPI Ingestion
description: Convert Swagger or OpenAPI sources into normalized graph-tool-call tool schemas.
---

# OpenAPI Ingestion

OpenAPI ingestion turns Swagger 2.0 or OpenAPI 3.x sources into normalized
`ToolSchema` objects. Each operation becomes a candidate tool with method, path,
operation id, summary, parameters, schemas, security hints, and source metadata.

## When To Use This

Use OpenAPI ingestion when a tool catalog starts from a REST API specification,
including Swagger UI URLs and direct JSON/YAML specification URLs.

Do not put product-specific auth tokens, cookies, database ids, or UI state in
the engine. Store those in the adapter and attach them only at execution time.

## Minimal Example

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://example.com/swagger-ui/index.html")
tools = graph.retrieve("find customer orders", top_k=8)
```

## Direct Graphify Entry Point

```python
from graph_tool_call.graphify import ingest_openapi_graphify

artifact = ingest_openapi_graphify("openapi.json")
print(artifact["metadata"]["tool_count"])
```

## Stable Metadata

OpenAPI-derived tools may include:

| Field | Purpose |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | Operation path |
| `metadata.openapi.operation_id` | Stable operation identifier when available |
| `metadata.openapi.parameters` | Query, path, header, and cookie parameters |
| `metadata.api_contract` | Engine-level consumes, produces, and links |
| `metadata.ai_metadata` | Deterministic semantic action/resource/module fields |

## Related Pages

- [IO Contracts](./io-contracts.md)
- [Semantic Build](./semantic-build.md)
- [Readiness Diagnostics](./readiness-diagnostics.md)
