---
title: MCP Server
description: Expose graph-tool-call retrieval capabilities through an MCP server.
---

# MCP Server

The MCP server exposes graph-tool-call capabilities through the
Model Context Protocol. Use it when an MCP-compatible client should search a
large catalog through a small set of gateway tools instead of seeing every
backend tool at once.

## Start From A Source

```bash
graph-tool-call serve \
  --source ./openapi.json \
  --transport stdio
```

Use multiple `--source` flags to combine catalogs:

```bash
graph-tool-call serve \
  --source ./orders.openapi.json \
  --source ./members.openapi.json
```

## Start From A Saved Graph

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call serve --graph graph.json --transport stdio
```

Serving from a saved graph avoids rebuilding on every process start.

## HTTP Transports

```bash
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

Bind to a private interface by default. Put external exposure behind your own
network and auth controls.

## What The Server Should Own

The server can own:

- loading sources or graphs
- searching tools
- returning compact candidate lists
- exposing graph-tool-call capabilities as MCP tools

The server should not own:

- production user auth
- tenant-specific policy
- raw downstream API secrets
- product database writes

## Production Notes

- Prefer pre-built graphs for predictable startup.
- Keep `--allow-private-hosts` limited to trusted infrastructure.
- Use `--top-k` style limits in clients or wrappers to keep tool context small.
- Log query, selected tool, and evidence, not secret values.

## Related Pages

- [MCP Ingestion](../build/mcp-ingestion.md)
- [MCP Proxy](./mcp-proxy.md)
- [CLI](../reference/cli.md)
