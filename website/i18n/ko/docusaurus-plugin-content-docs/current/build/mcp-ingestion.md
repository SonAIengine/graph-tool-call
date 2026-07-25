---
title: MCP Ingestion
description: MCP tool definition을 같은 graph engine에서 검색하고 plan할 수 있게 정규화합니다.
---

# MCP Ingestion

MCP ingestion은 model-context-protocol tool definition을 OpenAPI, Python tool과
같은 `ToolSchema` 표면으로 매핑합니다.

## Catalog 안에서의 역할

MCP tool은 enterprise OpenAPI보다 runtime description이 나은 경우가 많지만,
그래도 graph retrieval의 이점을 얻습니다.

- consistent annotation
- category와 relation analysis
- candidate filtering
- LLM용 compact tool list
- shared validation gate

## Adapter Boundary

MCP server credential이나 runtime transport state는 graph engine이 소유하지
않습니다. 연결 정보는 MCP proxy에 두고, graph에는 정규화된 schema를 전달합니다.

## 관련 문서

- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
