---
title: MCP Server
description: graph-tool-call retrieval 기능을 MCP server로 노출합니다.
---

# MCP Server

MCP server는 graph-tool-call 기능을 Model Context Protocol로 노출합니다.
MCP-compatible client가 모든 backend tool을 한꺼번에 보는 대신, 작은 gateway
tool surface를 통해 대형 catalog를 검색하게 만들 때 사용합니다.

## Source에서 시작

```bash
graph-tool-call serve \
  --source ./openapi.json \
  --transport stdio
```

여러 source를 합칠 수도 있습니다.

```bash
graph-tool-call serve \
  --source ./orders.openapi.json \
  --source ./members.openapi.json
```

## 저장된 graph에서 시작

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call serve --graph graph.json --transport stdio
```

저장된 graph를 쓰면 process start 때마다 rebuild하지 않아도 됩니다.

## HTTP transport

```bash
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

기본은 private interface에 bind하는 것이 안전합니다. 외부 노출은 별도 network
및 auth control 뒤에 두세요.

## Server가 책임질 것

- source 또는 graph load
- tool search
- compact candidate list 반환
- graph-tool-call capability를 MCP tool로 노출

책임지지 말아야 할 것:

- 운영 사용자 인증
- tenant-specific policy
- downstream API secret 원문
- product DB write

## 관련 문서

- [MCP Ingestion](../build/mcp-ingestion.md)
- [MCP Proxy](./mcp-proxy.md)
- [CLI](../reference/cli.md)
