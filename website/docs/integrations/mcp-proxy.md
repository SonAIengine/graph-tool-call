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

## Retrieval Behavior

The proxy uses graph-tool-call to:

- ingest backend tool schemas
- normalize descriptions and annotations
- search with keyword and optional embedding signals
- return a compact candidate set
- preserve evidence for debugging

## When Not To Use It

Do not add a proxy when:

- the backend exposes only a handful of tools
- the client needs complete raw backend capability discovery
- product policy must be enforced inside a dedicated backend adapter
- latency is more important than tool catalog reduction

## Related Pages

- [MCP Server](./mcp-server.md)
- [MCP Ingestion](../build/mcp-ingestion.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
