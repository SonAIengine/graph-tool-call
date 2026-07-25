---
title: MCP Proxy
description: 여러 MCP backend를 aggregate/filter해서 agent에 노출합니다.
---

# MCP Proxy

MCP proxy는 MCP client와 하나 이상의 backend MCP server 사이에 위치합니다.
backend tool 위에 searchable graph를 만들고, client에는 더 작고 필터링된 tool
surface를 노출합니다.

client가 너무 많은 tool을 보거나 여러 backend를 하나의 catalog처럼 검색해야
할 때 사용합니다.

## Proxy 실행

```bash
graph-tool-call proxy \
  --config .mcp.json \
  --top-k 10 \
  --passthrough-threshold 30
```

`--passthrough-threshold`는 작은 catalog를 단순하게 유지하기 위한 값입니다.
backend tool 수가 threshold보다 작으면 강한 filtering 없이 pass-through할 수
있습니다.

## HTTP transport

```bash
graph-tool-call proxy \
  --config proxy-config.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

## Config input

proxy는 일반 `.mcp.json` 스타일 파일이나 graph-tool-call proxy config를 읽을
수 있습니다.

```json
{
  "mcpServers": {
    "orders": {
      "command": "python",
      "args": ["orders_server.py"]
    }
  }
}
```

가능하면 backend credential은 runtime secret manager에 둡니다.

## Retrieval behavior

proxy는 graph-tool-call을 사용해 다음을 수행합니다.

- backend tool schema ingest
- description과 annotation normalize
- keyword와 optional embedding signal search
- compact candidate set 반환
- debugging을 위한 evidence 보존

## 관련 문서

- [MCP Server](./mcp-server.md)
- [MCP Ingestion](../build/mcp-ingestion.md)
- [Tool Graph 검색](../search/tool-graph-search.mdx)
