# Docker And Kubernetes

Build the checked-out source and run a private Streamable HTTP MCP service:

```bash
docker build -t graph-tool-call:local .
docker run --rm -p 8000:8000 graph-tool-call:local \
  --source https://petstore3.swagger.io/api/v3/openapi.json
```

- MCP endpoint: `http://127.0.0.1:8000/mcp`
- liveness: `GET /healthz`
- readiness and tool count: `GET /readyz`

The image runs as non-root. The starting Kubernetes manifest is
`deploy/kubernetes/mcp-server.yaml`. Keep the service private or place it
behind an authenticated AWS AgentCore, Microsoft Foundry, or equivalent MCP
gateway. Never put downstream credentials in graph artifacts or tool schemas.

`/readyz` returns HTTP 503 when a configured startup catalog fails to load or
contains no tools. Source-less servers remain ready so `load_source` can
populate them dynamically.
