---
title: Docker And Kubernetes
description: Run graph-tool-call as a private Streamable HTTP MCP service.
---

# Docker And Kubernetes

The production-neutral deployment shape is a private MCP service. Keep
credentials and public ingress in the host platform or a managed gateway.

## Build And Run

```bash
docker build -t graph-tool-call:local .
docker run --rm -p 8000:8000 graph-tool-call:local \
  --source https://petstore3.swagger.io/api/v3/openapi.json
```

The image:

- installs the checked-out source with MCP and OpenAPI extras;
- runs as a non-root user;
- defaults to Streamable HTTP on `0.0.0.0:8000`;
- exposes MCP at `/mcp`;
- checks `/healthz` with a Docker health check.

For a stable production startup, build a graph artifact ahead of time and
mount it read-only:

```bash
graph-tool-call ingest ./openapi.json -o graph.json
docker run --rm -p 8000:8000 \
  -v "$PWD/graph.json:/data/graph.json:ro" \
  graph-tool-call:local --graph /data/graph.json
```

## Kubernetes

Apply the checked-in starting manifest after replacing the image and source:

```bash
kubectl apply -f deploy/kubernetes/mcp-server.yaml
kubectl port-forward service/graph-tool-call 8000:8000
curl http://127.0.0.1:8000/readyz
```

The manifest uses a ClusterIP service, a read-only filesystem, a non-root
security context, resource limits, and HTTP probes. Tune the limits and add
organization policy for the target cluster.

## Managed Gateways

For AWS AgentCore or Microsoft Foundry, deploy this service on a private
container platform and register `https://SERVICE/mcp` as a remote MCP target.
Let the managed gateway own inbound identity, downstream credential injection,
approval, and audit policy.

Do not place downstream API tokens in graph artifacts, MCP configuration files,
tool descriptions, or model-visible arguments.

## Verification

```bash
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/readyz
```

A complete smoke test also initializes an MCP client, calls `search_tools`, and
checks that `get_tool_schema` returns the selected tool contract.

`/readyz` returns HTTP 503 when a configured startup source cannot be loaded or
produces no tools. A server started without a source stays ready with
`catalog_ready: false` because clients can populate it through `load_source`.
