# Quickstart

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

## Inspect an API Collection

```bash
graph-tool-call inspect-openapi ./openapi.json --json
```

Use this before putting a large OpenAPI collection into an agent. The report
shows schema coverage, contract coverage, graph readiness, semantic quality, and
stable issue codes.

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

