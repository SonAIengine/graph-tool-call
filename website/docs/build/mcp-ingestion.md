---
title: MCP Ingestion
description: Normalize MCP tool definitions so they can be searched and planned with the same graph engine.
---

# MCP Ingestion

MCP ingestion maps Model Context Protocol tool definitions into the same
`ToolSchema` surface used by OpenAPI and Python tools.

The contract follows the
[MCP tool schema](https://modelcontextprotocol.io/specification/2025-11-25/schema):
`name`, display `title`, `inputSchema`, optional `outputSchema`, behavioral
annotations, and `execution.taskSupport`.

## Role In The Catalog

MCP tools usually arrive with better runtime descriptions than raw enterprise
OpenAPI specs, but they still benefit from graph retrieval:

- consistent annotations
- category and relation analysis
- candidate filtering
- compact tool lists for the LLM
- shared validation gates

## Ingest A Tool List

Use `ingest_source()` when you have a bare tool array or a JSON-RPC
`tools/list` response. The adapter reports pagination and schema coverage:

```python
from graph_tool_call import ingest_source

result = ingest_source(
    tools_list_response,
    format_hint="mcp-tools",
    required_capabilities={"input_schema"},
)
print(result.ready, result.metadata["output_schema_coverage"])
```

Use `ingest_mcp_tools()` when an application adapter has already fetched and
fully paginated the tool rows.

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
            "outputSchema": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
            },
        }
    ],
    server_name="filesystem",
)
```

The parser preserves MCP annotations such as `readOnlyHint`,
`destructiveHint`, and enum values on parameters. Nested input/output schemas
also produce `api_contract.consumes` and `api_contract.produces` evidence for
graph construction and planning.

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

This convenience path handles a single `tools/list` response. It rejects
`nextCursor` by default because a complete paginated catalog requires a
session-aware MCP client. Applications such as XGEN MCP Station should fetch
every page and pass the combined rows to `ingest_source()` or
`ingest_mcp_tools()`. `allow_partial_catalog=True` is only for explicit preview
workflows.

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
| `metadata.mcp` | display title, schema provenance, task support, trust state |
| `metadata.request_body_schema` | complete MCP `inputSchema` |
| `metadata.response_schema` | complete MCP `outputSchema`, when supplied |
| `metadata.api_contract` | consumes/produces rows derived from both schemas |
| `tags` | includes the server name when available |
| `annotations` | MCP safety and behavior hints |
| `parameters` | normalized input schema properties |

## Adapter Boundary

The graph engine should not own MCP server credentials or runtime transport
state. Keep connection details in the MCP proxy, then pass normalized schemas to
the graph.

Catalog ingest does **not** make a tool executable. An application must bind
the canonical tool to a live MCP session and implement `tools/call`, task
polling, authentication, consent, and result validation. Canonical metadata
therefore starts with `execution.executable: false`.

MCP annotations and descriptions are untrusted server input. Set
`annotations_trusted=True` only after the application has authenticated and
approved the server. The flag records provenance; it does not bypass execution
confirmation or policy checks.

If `nextCursor` is present, ingest is blocked with `mcp_catalog_incomplete`.
Fetch every page before production registration. `allow_partial_catalog=True`
is intended only for explicit preview workflows.

The default limits are 1,000 tools, 64 schema levels, and 10,000 schema nodes
per input/output schema. Override `max_tools`, `max_schema_depth`, or
`max_schema_nodes` only inside a trusted application boundary.

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| invalid JSON | server did not return a JSON-RPC response | verify endpoint and transport |
| no tools detected | response lacks `result.tools` or `tools` | inspect the MCP server `tools/list` output |
| catalog incomplete | `nextCursor` is present | fetch and combine every page |
| output coverage below gate | tools omit `outputSchema` | keep search-only readiness or improve the server contract |
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
