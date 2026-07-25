---
title: MCP Ingestion
description: Normalize MCP tool definitions so they can be searched and planned with the same graph engine.
---

# MCP Ingestion

MCP ingestion maps model-context-protocol tool definitions into the same
`ToolSchema` surface used by OpenAPI and Python tools.

## Role In The Catalog

MCP tools usually arrive with better runtime descriptions than raw enterprise
OpenAPI specs, but they still benefit from graph retrieval:

- consistent annotations
- category and relation analysis
- candidate filtering
- compact tool lists for the LLM
- shared validation gates

## Ingest A Tool List

Use `ingest_mcp_tools()` when the adapter already has an MCP `tools/list`
response.

```python
from graph_tool_call.ingest.mcp import ingest_mcp_tools

schemas = ingest_mcp_tools(
    [
        {
            "name": "read_file",
            "description": "Read a file",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
            "annotations": {"readOnlyHint": True},
        }
    ],
    server_name="filesystem",
)
```

The parser preserves MCP annotations such as `readOnlyHint`,
`destructiveHint`, and enum values on parameters.

## Ingest Into A Graph

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_mcp_tools(mcp_tools, server_name="filesystem")

for tool in graph.retrieve("read a configuration file", top_k=3):
    print(tool.name)
```

`ToolGraph.ingest_mcp_tools()` registers the schemas and can run dependency
detection using the same graph relation logic as other tool sources.

## Fetch From An MCP Endpoint

For HTTP JSON-RPC MCP endpoints that support `tools/list`:

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_mcp_server(
    "https://mcp.example.com/mcp",
    timeout=30,
    max_response_bytes=5_000_000,
)
```

Private hosts are blocked by default. Enable them only from trusted
infrastructure:

```python
graph.ingest_mcp_server(
    "http://127.0.0.1:3000/mcp",
    allow_private_hosts=True,
)
```

## Normalized Metadata

| Field | Purpose |
| --- | --- |
| `metadata.source` | set to `mcp` |
| `metadata.mcp_server` | server name from argument, serverInfo, or hostname |
| `tags` | includes the server name when available |
| `annotations` | MCP safety and behavior hints |
| `parameters` | normalized input schema properties |

## Adapter Boundary

The graph engine should not own MCP server credentials or runtime transport
state. Keep connection details in the MCP proxy, then pass normalized schemas to
the graph.

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| invalid JSON | server did not return a JSON-RPC response | verify endpoint and transport |
| no tools detected | response lacks `result.tools` or `tools` | inspect the MCP server `tools/list` output |
| private host blocked | endpoint is local/internal | opt in from trusted infrastructure only |
| destructive tool ranked too high | annotations or query intent are weak | preserve `destructiveHint` and add validation cases |

## Validation

```bash
poetry run pytest tests/test_ingest_mcp.py tests/test_mcp_annotations.py -q
```

## Related Pages

- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
