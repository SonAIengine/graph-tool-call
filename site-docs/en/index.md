# graph-tool-call

`graph-tool-call` is a graph-structured tool retrieval engine for LLM agents.
It turns OpenAPI specs, MCP tools, and Python functions into a searchable tool
graph, then returns the small set of tools and workflow evidence an agent needs.

## Why It Exists

Large tool catalogs break agents in two ways:

- Too many tool definitions overflow the model context.
- Similarity search can find one matching tool but miss the workflow around it.

`graph-tool-call` solves this by combining keyword search, graph expansion,
OpenAPI contracts, semantic metadata, target selection, and trace evidence.

## What You Can Build

- Search thousands of tools without sending every tool schema to the LLM.
- Convert OpenAPI collections into execution-ready tool graphs.
- Select the right target tool with deterministic evidence before asking an LLM.
- Validate search, planning, and execution quality with repeatable gates.
- Feed successful and failed run traces back into future ranking decisions.

## Start Here

- New to the library: [Quickstart](getting-started/quickstart.md)
- Building from Swagger/OpenAPI: [OpenAPI Collections](guides/openapi-collections.md)
- Integrating with XGEN: [XGEN Integration](guides/xgen-integration.md)
- Checking quality: [Benchmarks](validation/benchmarks.md)
- Looking for APIs: [Public API](reference/public-api.md)

## Minimal Example

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

for tool in graph.retrieve("find pets by status", top_k=5):
    print(tool.name, tool.description)
```

## Current Focus

The current roadmap focuses on large enterprise API collections:

- deterministic OpenAPI contract extraction
- semantic action/resource/module assignment
- target selection guards around LLM choices
- auth readiness diagnostics
- trace learning from successful and failed execution attempts

