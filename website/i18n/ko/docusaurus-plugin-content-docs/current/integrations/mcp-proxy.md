---
title: MCP Proxy
description: MCP backend를 aggregate/filter한 뒤 agent에 tool을 노출합니다.
---

# MCP Proxy

MCP proxy는 여러 backend를 aggregate하고 더 작은 tool surface를 client에 노출할
수 있습니다.

## 왜 Proxy를 쓰나

- backend를 분리해서 유지
- catalog filtering 적용
- LLM이 보기 전에 tool count 축소
- transport concern을 core graph engine 밖에 유지

## 관련 문서

- [MCP Server](./mcp-server.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
