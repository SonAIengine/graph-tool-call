# CLI Reference

```bash
pip install graph-tool-call           # core CLI
pip install graph-tool-call[mcp]      # + MCP server / proxy commands
```

## Commands at a glance

| Command | Purpose |
|---|---|
| `search`     | One-liner: ingest + retrieve in one step |
| `serve`      | Run as MCP server |
| `proxy`      | Run as MCP proxy (aggregates multiple MCP backends) |
| `ingest`     | Build a graph from a spec and save |
| `retrieve`   | Search a pre-built graph |
| `analyze`    | Print operational analysis (duplicates, conflicts, orphans) |
| `visualize`  | Export graph to HTML / GraphML |
| `info`       | Print graph statistics |
| `dashboard`  | Launch interactive Dash Cytoscape UI |

---

## `search` — one-liner search

```bash
# Ingest + retrieve in one step
graph-tool-call search "cancel order" \
  --source https://api.example.com/openapi.json

graph-tool-call search "delete user" \
  --source ./openapi.json --scores --json
```

Useful for quick exploration without saving the graph.

---

## `serve` — MCP server

```bash
# Single source
graph-tool-call serve --source https://api.example.com/openapi.json

# Pre-built graph
graph-tool-call serve --graph prebuilt.json

# Multiple sources
graph-tool-call serve \
  -s https://api1.com/spec.json \
  -s https://api2.com/spec.json

# Remote (SSE / streamable HTTP)
graph-tool-call serve --source api.json --transport sse --host 0.0.0.0 --port 8000
graph-tool-call serve --source api.json --transport streamable-http --port 8000
```

See [MCP Server integration guide](integrations/mcp-server.md) for client configuration.

---

## `proxy` — MCP proxy

```bash
graph-tool-call proxy --config ~/backends.json
graph-tool-call proxy --config backends.json --transport sse --port 8000
graph-tool-call proxy --config backends.json --passthrough-threshold 50
```

See [MCP Proxy integration guide](integrations/mcp-proxy.md) for `backends.json` format.

---

## `ingest` — build and save a graph

```bash
graph-tool-call ingest https://api.example.com/openapi.json -o graph.json
graph-tool-call ingest ./spec.yaml --embedding --organize
```

Flags:
- `-o, --output PATH` — output graph file (JSON)
- `--embedding` — enable embedding-based hybrid search
- `--organize` — auto-categorize tools into ontology

---

## `retrieve` — search a pre-built graph

```bash
graph-tool-call retrieve "query" -g graph.json -k 10
```

Flags:
- `-g, --graph PATH` — pre-built graph file
- `-k, --top-k N` — number of results
- `--scores` — print scores
- `--json` — JSON output

---

## `analyze` — operational analysis

```bash
graph-tool-call analyze graph.json --duplicates --conflicts
```

Prints duplicate tools, conflict pairs, orphan tools, category coverage.

---

## `visualize` — export to HTML / GraphML

```bash
graph-tool-call visualize graph.json -f html       # interactive HTML
graph-tool-call visualize graph.json -f graphml    # Gephi/yEd
graph-tool-call visualize graph.json -f cypher     # Neo4j
```

---

## `info` — graph statistics

```bash
graph-tool-call info graph.json
# → ToolGraph(tools=248, nodes=251, edges=1024)
```

---

## `dashboard` — interactive UI

```bash
graph-tool-call dashboard graph.json --port 8050
```

Launches the Dash Cytoscape interactive dashboard for graph inspection and retrieval testing. Requires `pip install graph-tool-call[dashboard]`.
