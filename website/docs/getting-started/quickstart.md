---
title: Quickstart
description: Install graph-tool-call, search an OpenAPI spec, inspect readiness, and execute a simple operation.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

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

## See the Difference First

Run the offline demo to see why finding only the target tool is insufficient.
It uses the real retriever, target selector, and typed dependency closure.

```bash
uvx graph-tool-call demo dependency-chain
```

```text
Selected target:
  refundOrder(order_id)

Required producer:
  findOrdersByEmail(email) -> order_id

Execution order:
  1. findOrdersByEmail
  2. refundOrder
```

## Search an OpenAPI Spec

Use the CLI when you want a fast smoke test. Use Python when you are wiring the
engine into an application or test suite.

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
uvx graph-tool-call search "create a new pet" \
  --source https://petstore.swagger.io/v2/swagger.json \
  --top-k 5 \
  --scores
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
results = graph.retrieve_with_scores("create a new pet", top_k=5)

for result in results:
    print(result.tool.name, result.score, result.confidence)
```

  </TabItem>
  <TabItem value="evidence" label="Evidence">

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
response = retrieve_graphify(
    graph,
    "create a new pet",
    top_k=5,
    include_evidence=True,
)

first = response["results"][0]
print(first["name"])
print(first["score_breakdown"])
```

  </TabItem>
</Tabs>

The CLI loads the source, creates a temporary graph, retrieves candidates, and
prints the strongest matches. Use this path to test a spec before writing code.

## Build a Tool Graph

Build a reusable graph when repeated searches should avoid re-ingesting the
source.

<Tabs>
  <TabItem value="python-cache" label="Python cache" default>

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

  </TabItem>
  <TabItem value="cli-ingest" label="CLI graph">

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "create a new pet" --graph graph.json --top-k 5
```

  </TabItem>
  <TabItem value="collection" label="Collection artifact">

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  -o collection.json \
  --context-field siteNo \
  --paging-field page,size
```

  </TabItem>
</Tabs>

Use the saved graph for local agent experiments. Use the collection artifact
when a product adapter or UI needs readiness, semantic, and edge-quality
metadata.

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
