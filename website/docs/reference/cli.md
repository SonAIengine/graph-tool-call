---
title: CLI
description: Command-line workflows for ingesting, inspecting, searching, serving, and executing tool graphs.
---

# CLI

The package exposes the `graph-tool-call` command. Use it to prototype a tool
catalog locally, generate collection artifacts for an adapter, run readiness
checks, or serve a filtered MCP tool surface.

```bash
graph-tool-call --version
graph-tool-call --help
```

## Command Overview

| Command | Use It For |
| --- | --- |
| `demo` | Run the offline target-plus-producer launch demonstration |
| `search` | One-shot ingest plus retrieval from an OpenAPI source or graph file |
| `ingest` | Build and save a reusable `ToolGraph` JSON file |
| `retrieve` | Search an already-built graph |
| `inspect-openapi` | Run deterministic OpenAPI readiness diagnostics |
| `build-openapi-collection` | Build a storage-ready collection artifact |
| `analyze` | Inspect graph structure, duplicates, conflicts, or orphan tools |
| `visualize` | Export HTML, GraphML, or Cypher graph views |
| `info` | Print node and edge summaries |
| `dashboard` | Launch the local interactive dashboard |
| `call` | Search and execute an OpenAPI tool through the built-in HTTP executor |
| `serve` | Run graph-tool-call as an MCP server |
| `proxy` | Aggregate and filter multiple MCP backends |

## Run The Offline Demo

The demo uses a fixed ecommerce contract and the real retrieval, target
selection, and dependency-closure pipeline. It needs no network or optional
dependency.

```bash
graph-tool-call demo dependency-chain
graph-tool-call demo dependency-chain --json
```

## Search Without A Build Step

Use `search` when you are exploring a spec and do not need a persisted artifact.

```bash
graph-tool-call search "find pets by status" \
  --source https://petstore3.swagger.io/api/v3/openapi.json \
  --top-k 8 \
  --scores
```

Return JSON for scripts or test fixtures:

```bash
graph-tool-call search "find pets by status" \
  --source ./openapi.json \
  --top-k 8 \
  --scores \
  --json
```

Use `--cache graph.json` for repeated local searches against the same source.

## Build And Retrieve

Use this workflow when the graph should be reused by a service, benchmark, or
manual inspection step.

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "cancel an order" --graph graph.json --top-k 8
graph-tool-call analyze graph.json --duplicates --orphans
```

Useful ingest flags:

| Flag | Purpose |
| --- | --- |
| `--required-only` | Keep only required OpenAPI parameters during ingest |
| `--include-deprecated` | Include deprecated operations |
| `--embedding [MODEL]` | Build an optional embedding index |
| `--organize` | Run automatic graph organization |
| `--llm PROVIDER/MODEL` | Use an LLM provider for ontology enrichment |
| `--allow-private-hosts` | Permit trusted private/internal URL loading |
| `--force` | Rebuild even when cache exists |

## Inspect OpenAPI Readiness

Run this before enabling plan or execute flows for a collection.

```bash
graph-tool-call inspect-openapi ./openapi.json
graph-tool-call inspect-openapi ./openapi.json --json
```

Classify product-specific field names without hard-coding them into the engine:

```bash
graph-tool-call inspect-openapi ./openapi.json \
  --context-field mallNo,siteNo \
  --paging-field page,size \
  --search-filter-field keyword,searchType
```

The report includes readiness score, issue codes, schema coverage, semantic
coverage, graph connectivity, and recommendations.

## Build A Collection Artifact

Use `build-openapi-collection` when a product adapter needs a single JSON
payload containing tools, graph, readiness, semantic summary, edge quality, and
source snapshot metadata.

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  -o collection.json \
  --context-field mallNo,siteNo \
  --paging-field page,size \
  --auth-field Authorization,X-API-Key
```

Alias options are generic `alias=canonical` mappings:

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  --resource-alias goods=product,item=product \
  --action-alias 조회=read,등록=create \
  --module-alias memberMgmt=member
```

Write to stdout for pipelines:

```bash
graph-tool-call build-openapi-collection ./openapi.json -o - | jq '.semantic_summary'
```

## Execute A Tool

`call` is useful for local smoke tests. Production adapters usually provide
their own executor so they can control auth, tenancy, retries, auditing, and
mutation safety.

```bash
graph-tool-call call "find pet by id" \
  --source ./openapi.json \
  --base-url https://petstore3.swagger.io/api/v3 \
  --args '{"petId": 1}' \
  --dry-run
```

Run without `--dry-run` only against trusted APIs:

```bash
graph-tool-call call "find pet by id" \
  --source ./openapi.json \
  --base-url https://petstore3.swagger.io/api/v3 \
  --args '{"petId": 1}'
```

## Serve Or Proxy MCP

Expose a graph as an MCP server:

```bash
graph-tool-call serve \
  --source ./openapi.json \
  --transport stdio
```

Serve over HTTP transport when the client supports it:

```bash
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

Aggregate multiple MCP backends:

```bash
graph-tool-call proxy \
  --config .mcp.json \
  --top-k 10 \
  --passthrough-threshold 30
```

## Visualize

```bash
graph-tool-call visualize graph.json -o graph.html
graph-tool-call visualize graph.json --format graphml -o graph.graphml
graph-tool-call visualize graph.json --format cypher -o graph.cypher
```

Use visualizations for local inspection. Large product UIs should usually render
clustered summaries or filtered subgraphs instead of drawing every edge at once.

## Exit-Code Guidance

The CLI uses non-zero exits for unrecoverable command errors such as invalid
JSON arguments, missing graph files, unsupported aliases, or no selected tool in
`call`. For validation pipelines, prefer `--json` output and assert on report
fields instead of parsing human-readable text.

## Related Pages

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
