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

## Adapter Boundary

The graph engine should not own MCP server credentials or runtime transport
state. Keep connection details in the MCP proxy, then pass normalized schemas to
the graph.

## Related Pages

- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
