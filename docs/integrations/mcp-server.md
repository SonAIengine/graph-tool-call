# MCP Server

Run graph-tool-call as an MCP server. Any MCP-compatible agent (Claude Code, Cursor, Windsurf, etc.) can use tool search with just a config entry.

## Quick start

```jsonc
// .mcp.json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve",
               "--source", "https://api.example.com/openapi.json"]
    }
  }
}
```

## Remote deployment (SSE / Streamable HTTP)

The MCP server supports remote transports for shared deployments:

```bash
# SSE transport
graph-tool-call serve --source api.json --transport sse --host 0.0.0.0 --port 8000

# Streamable HTTP
graph-tool-call serve --source api.json --transport streamable-http --port 8000
```

Client config for a remote MCP server:

```json
{
  "mcpServers": {
    "tool-search": {
      "url": "http://tool-search.internal:8000/sse"
    }
  }
}
```

## Exposed tools

The MCP server exposes 6 tools:

| Tool | Purpose |
|---|---|
| `search_tools` | Hybrid search across the tool graph |
| `get_tool_schema` | Fetch the full schema for a specific tool |
| `execute_tool` | Execute an OpenAPI tool directly |
| `list_categories` | List ontology categories |
| `graph_info` | Graph statistics (nodes, edges, relations) |
| `load_source` | Hot-load a new source into the running server |

## Search results include workflow guidance

Search results contain **relations** between tools and a **suggested execution order**:

```json
{
  "tools": [
    {
      "name": "createOrder",
      "relations": [
        {"target": "getOrder", "type": "precedes",
         "hint": "Call this tool before getOrder"}
      ]
    },
    {"name": "getOrder", "prerequisites": ["createOrder"]}
  ],
  "workflow": {"suggested_order": ["createOrder", "getOrder", "updateOrderStatus"]}
}
```

This lets the agent plan multi-step calls in one turn instead of round-tripping per tool.

## Multiple sources

Pass `-s` multiple times to merge several specs into one graph:

```bash
graph-tool-call serve \
  -s https://api1.example.com/openapi.json \
  -s https://api2.example.com/openapi.json
```

Cross-source duplicate detection automatically dedupes tools that appear in multiple specs.

## Pre-built graph

Build the graph once, serve it many times:

```bash
graph-tool-call ingest https://api.example.com/openapi.json -o graph.json
graph-tool-call serve --graph graph.json
```

See the [CLI reference](../cli.md) for the full `serve` flag list.
