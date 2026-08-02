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

## Client Configuration

Most MCP clients can start the server with a local command. Keep the catalog
pre-built for large OpenAPI collections so the client does not wait for ingest.

```json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve", "--graph", "graph.json"]
    }
  }
}
```

Use `--source` during development and `--graph` in repeatable environments.
When a spec lives on an internal URL, pair it with your network policy and only
enable `--allow-private-hosts` for trusted infrastructure.

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

Streamable HTTP also exposes orchestration probes:

- `GET /healthz` for process liveness
- `GET /readyz` for readiness and catalog tool count

## Docker

The repository image builds the checked-out source and starts a non-root
Streamable HTTP server on `0.0.0.0:8000`:

```bash
docker build -t graph-tool-call:local .
docker run --rm -p 8000:8000 graph-tool-call:local \
  --source https://petstore3.swagger.io/api/v3/openapi.json

curl http://127.0.0.1:8000/healthz
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Keep it on a private network
or place it behind an authenticated MCP gateway before external exposure.

For Kubernetes, start with `deploy/kubernetes/mcp-server.yaml` and replace the
image and `OPENAPI_SOURCE` value.

| Transport | Use When | Notes |
| --- | --- | --- |
| `stdio` | A desktop or agent client starts the process directly | simplest local setup |
| `sse` | A client expects server-sent events | useful for older MCP deployments |
| `streamable-http` | A remote client connects over HTTP | bind privately and add your own auth layer |

## Tool Surface

The server intentionally exposes a small gateway surface. The LLM should search
first, inspect the selected schema, then call only when the execution adapter is
appropriate for the environment.

| MCP tool | Purpose | Typical Next Step |
| --- | --- | --- |
| `search_tools` | Rank tools for a natural-language query and return compact candidates | call `get_tool_schema` for the best target |
| `get_tool_schema` | Return exact parameters, method, path, category, and tags | prepare arguments or hand off to a product runner |
| `list_categories` | Show category counts for catalog orientation | refine the query or browse a domain |
| `graph_info` | Show graph size, node types, edge types, and source metadata | diagnose build quality |
| `execute_tool` | Execute an OpenAPI tool through the built-in HTTP executor | use mostly for demos or controlled internal tooling |
| `load_source` | Add another OpenAPI source at runtime | refresh small catalogs without restarting |

## Recommended Workflow

```text
search_tools("find refund-ready orders", top_k=5)
  -> get_tool_schema("getRefundableOrders")
  -> execute through your application adapter
```

For production systems, keep authentication, tenant policy, audit logging, and
side-effect controls in the product adapter. `execute_tool` is useful for local
testing, but it should not become the place where product-specific auth rules
live.

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

## Failure Modes

| Symptom | Likely Cause | Check |
| --- | --- | --- |
| `No tools loaded` | the server started without a valid source or graph | run `graph-tool-call ingest SOURCE -o graph.json` first |
| candidate list is too broad | weak tool descriptions or missing semantic metadata | inspect `graph_info` and rebuild the artifact |
| schema lacks parameters | OpenAPI request schema was missing or generic | run the OpenAPI readiness report |
| private URL fails to load | URL safety policy blocked internal hosts | use a saved graph or explicitly allow trusted private hosts |
| API call fails at execution | auth/base URL belongs in the product adapter | inspect runner/auth readiness outside the MCP server |

## Validate The Integration

```bash
poetry run pytest tests/test_mcp_server.py -q
```

For a real client smoke test, start the server from a saved graph, run
`search_tools`, confirm that `get_tool_schema` returns parameters for the
selected tool, and keep raw secrets out of the transcript.

## Related Pages

- [MCP Ingestion](../build/mcp-ingestion.md)
- [MCP Proxy](./mcp-proxy.md)
- [CLI](../reference/cli.md)
