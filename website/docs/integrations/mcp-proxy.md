---
title: MCP Proxy
description: Aggregate and filter MCP backends before exposing tools to an agent.
---

# MCP Proxy

The MCP proxy can aggregate multiple backends and expose a smaller tool surface
to clients.

## Why Use A Proxy

- keep backends separate
- apply catalog filtering
- reduce tool count before the LLM sees it
- keep transport concerns outside the core graph engine

## Related Pages

- [MCP Server](./mcp-server.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
