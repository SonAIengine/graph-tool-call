---
title: MCP Proxy
description: Aggregate and filter MCP backends before exposing tools to an agent.
---

# MCP Proxy

The MCP proxy sits between an MCP client and one or more backend MCP servers. It
builds a searchable graph over backend tools and exposes a smaller, filtered
tool surface to the client.

Use a proxy when the client would otherwise see too many tools or when several
backend servers need to be searched as one catalog.

## Run The Proxy

```bash
graph-tool-call proxy \
  --config .mcp.json \
  --top-k 10 \
  --passthrough-threshold 30
```

`--passthrough-threshold` keeps small catalogs simple. If a backend exposes fewer
tools than the threshold, the proxy may pass them through without aggressive
filtering.

The proxy has two operating modes:

| Mode | Trigger | Client Sees | Use It For |
| --- | --- | --- | --- |
| gateway | catalog size is above `--passthrough-threshold` | `search_tools`, `get_tool_schema`, `call_backend_tool`, then matched backend tools | large or multi-server catalogs |
| passthrough | catalog size is below the threshold | backend tools directly | small catalogs where filtering would add friction |

## HTTP Transport

```bash
graph-tool-call proxy \
  --config proxy-config.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

## Config Inputs

The proxy can read a normal `.mcp.json` style file or a graph-tool-call proxy
config. Keep backend credentials in your runtime secret manager where possible.

```json
{
  "mcpServers": {
    "orders": {
      "command": "python",
      "args": ["orders_server.py"]
    }
  }
}
```

When multiple backends expose the same tool name, the proxy keeps names
callable by prefixing duplicates with the backend name. That avoids silent
collisions while preserving direct tool calls after search.

## Retrieval Behavior

The proxy uses graph-tool-call to:

- ingest backend tool schemas
- normalize descriptions and annotations
- search with keyword and optional embedding signals
- return a compact candidate set
- preserve evidence for debugging

## Gateway Workflow

In gateway mode, the client should search before calling a backend tool.

```text
tools/list
  -> search_tools({"query": "create a customer refund", "top_k": 8})
  -> tools/list refresh exposes matched backend tools
  -> get_tool_schema({"tool_name": "orders.create_refund"})
  -> call matched backend tool directly
```

`call_backend_tool` is a fallback for clients that cannot call dynamically
injected backend tools. Prefer direct calls when the client supports them.

## Tuning

| Option | Effect | Practical Guidance |
| --- | --- | --- |
| `--top-k` | default number of tools returned by `search_tools` | keep this small enough for the client context window |
| `--embedding` | enables optional embedding signals | use when descriptions are rich enough to justify the cost |
| `--cache` | persists backend tool metadata and retrieval state | use for slower backend startup |
| `--passthrough-threshold` | switches between passthrough and gateway mode | lower it when clients struggle with many tools |

## When Not To Use It

Do not add a proxy when:

- the backend exposes only a handful of tools
- the client needs complete raw backend capability discovery
- product policy must be enforced inside a dedicated backend adapter
- latency is more important than tool catalog reduction

## Failure Modes

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| only meta-tools appear | gateway mode is active and no search has been run yet | call `search_tools` and refresh `tools/list` |
| direct backend tool is missing | matched tools were not injected or client cached `tools/list` | call `get_tool_schema` or `call_backend_tool` as fallback |
| duplicate-looking names | multiple backends exposed the same tool name | inspect backend-prefixed names in search results |
| poor ranking | backend descriptions are thin or generic | add annotations or ingest richer metadata |
| startup is slow | every backend is queried on process start | enable `--cache` or reduce backend scope |

## Validate The Integration

```bash
poetry run pytest tests/test_mcp_proxy.py -q
```

For a manual smoke test, run the proxy with a small fixture backend, confirm
gateway versus passthrough mode, search for one task, and verify that the
matched tool can be called either directly or through `call_backend_tool`.

## Related Pages

- [MCP Server](./mcp-server.md)
- [MCP Ingestion](../build/mcp-ingestion.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
