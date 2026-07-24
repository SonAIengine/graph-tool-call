# CLI

The package exposes the `graph-tool-call` command.

## Search

```bash
graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

## Inspect OpenAPI

```bash
graph-tool-call inspect-openapi ./openapi.json
graph-tool-call inspect-openapi ./openapi.json --json
```

## Typical Workflow

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "cancel an order" --graph graph.json --top-k 8
graph-tool-call analyze graph.json
```

Run `graph-tool-call --help` for the version-specific command list.

