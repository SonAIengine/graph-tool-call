---
title: Quickstart
description: Install graph-tool-call, search an OpenAPI spec, inspect readiness, and execute a simple operation.
---

# Quickstart

This quickstart shows the smallest useful loop:

1. install the package
2. search an OpenAPI spec
3. build a graph in Python
4. inspect collection readiness
5. execute a simple operation when safe

## Install

```bash
pip install graph-tool-call
```

Install only the extras you need:

```bash
pip install "graph-tool-call[openapi]"
pip install "graph-tool-call[korean]"
pip install "graph-tool-call[mcp]"
pip install "graph-tool-call[all]"
```

## Search an OpenAPI Spec

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

The CLI loads the source, creates a temporary graph, retrieves candidates, and
prints the strongest matches. Use this path to test a spec before writing code.

## Build a Tool Graph

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.graph.json",
)

results = graph.retrieve("create a new pet", top_k=5)
for tool in results:
    print(tool.name)
```

For deeper debugging, request evidence:

```python
from graph_tool_call.graphify import retrieve_graphify

rows = retrieve_graphify(
    graph,
    "create a new pet",
    top_k=5,
    include_evidence=True,
)

for row in rows:
    print(row["tool_name"], row["score_breakdown"])
```

## Inspect an API Collection

```bash
graph-tool-call inspect-openapi ./openapi.json --json
```

Use this before putting a large OpenAPI collection into an agent. The report
shows schema coverage, contract coverage, graph readiness, semantic quality, and
stable issue codes.

Typical fields to check:

| Field | Why It Matters |
| --- | --- |
| `readiness_score` | high-level collection readiness |
| `status` | `ready`, `warning`, or `blocked` |
| `issues[].code` | stable reason codes for repair |
| `semantic_summary` | action/resource/module coverage |
| `edge_quality_summary` | whether graph edges have useful evidence |

## Plan and Execute

```python
result = graph.execute(
    "addPet",
    {"name": "Buddy", "status": "available"},
    base_url="https://petstore3.swagger.io/api/v3",
)
```

Execution metadata is derived from the OpenAPI contract: path/query/header/body
locations, content types, security requirements, and response shape.

Do not execute mutating APIs in production-like environments until auth
readiness, required inputs, and cleanup policies are configured by your adapter.

## Next Steps

- Understand the engine pipeline: [Mental Model](./mental-model.md)
- Build from large specs: [OpenAPI Ingestion](../build/openapi-ingestion.md)
- Inspect ranking evidence: [Retrieval Signals](../search/retrieval-signals.md)
- Validate a collection: [Quality Gates](../guides/quality-gates.md)
