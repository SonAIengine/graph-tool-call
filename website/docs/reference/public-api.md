# Public API

This page lists the public modules and entry points that adapters should rely on.
Avoid importing private helpers from internal modules unless the documentation
explicitly says they are stable.

## Package Exports

```python
from graph_tool_call import ToolGraph, ToolSchema
```

## ToolGraph

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
tools = graph.retrieve("find customer orders", top_k=8)
ranked = graph.retrieve_with_scores("find customer orders", top_k=8)
report = graph.analyze()
```

## Tool Schema

```python
from graph_tool_call import ToolSchema
```

`ToolSchema` is the normalized tool representation used by ingest, graph build,
retrieval, planning, and adapters.

## Graphify

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    ingest_openapi_graphify,
    retrieve_graphify,
)
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index
```

Use these functions when building large API collections from OpenAPI specs.

## Planflow

```python
from graph_tool_call.plan import PathSynthesizer, PlanRunner
```

`PathSynthesizer` turns selected targets and contracts into execution plans.
`PlanRunner` streams structured execution events.

## Learning

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
)
```

Learning APIs store scrubbed trace evidence and optional promoted suggestions.
