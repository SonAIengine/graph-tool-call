---
title: Docker와 Kubernetes
description: graph-tool-call을 private Streamable HTTP MCP service로 실행합니다.
---

# Docker와 Kubernetes

운영 환경의 기본 형태는 private MCP service입니다. credential과 public ingress는
host platform 또는 managed gateway에서 담당합니다.

## Build와 실행

```bash
docker build -t graph-tool-call:local .
docker run --rm -p 8000:8000 graph-tool-call:local \
  --source https://petstore3.swagger.io/api/v3/openapi.json
```

image는 checked-out source를 설치하고 non-root 사용자로 Streamable HTTP server를
`0.0.0.0:8000`에서 실행합니다. MCP endpoint는 `/mcp`, probe는 `/healthz`와
`/readyz`입니다.

운영에서는 graph artifact를 먼저 만들고 read-only mount하는 방식을 권장합니다.

```bash
graph-tool-call ingest ./openapi.json -o graph.json
docker run --rm -p 8000:8000 \
  -v "$PWD/graph.json:/data/graph.json:ro" \
  graph-tool-call:local --graph /data/graph.json
```

## Kubernetes

image와 source를 수정한 뒤 기본 manifest를 적용합니다.

```bash
kubectl apply -f deploy/kubernetes/mcp-server.yaml
kubectl port-forward service/graph-tool-call 8000:8000
curl http://127.0.0.1:8000/readyz
```

manifest는 ClusterIP, read-only filesystem, non-root security context, HTTP probe를
사용합니다. 실제 cluster 정책에 맞는 resource와 network policy를 추가해야 합니다.

설정한 시작 source를 불러오지 못하거나 도구가 하나도 생성되지 않으면
`/readyz`는 HTTP 503을 반환합니다. source 없이 시작한 서버는
`load_source`로 나중에 채울 수 있으므로 `catalog_ready: false`인 상태에서도
ready로 유지됩니다.

## Managed Gateway

AWS AgentCore 또는 Microsoft Foundry에서는 private container platform에 이 service를
배포하고 `https://SERVICE/mcp`를 remote MCP target으로 등록합니다. inbound identity,
downstream credential injection, approval, audit policy는 managed gateway가 담당합니다.

downstream API token을 graph artifact, MCP config, tool description 또는 model-visible
argument에 넣지 않습니다.
