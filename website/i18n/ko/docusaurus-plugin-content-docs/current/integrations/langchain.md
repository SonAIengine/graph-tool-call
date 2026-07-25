---
title: LangChain
description: LangChain tool adapter와 graph-tool-call retrieval을 함께 사용합니다.
---

# LangChain

LangChain integration은 model에 tool set을 구성하기 전에 graph-tool-call을 retrieval
및 filtering layer로 사용하는 방식이 좋습니다.

## Guidance

- compact candidate set을 먼저 retrieve합니다.
- debugging을 위해 evidence를 보존합니다.
- execution credential은 host application에 둡니다.
- catalog를 넓히기 전에 tool count와 quality를 검증합니다.

## 관련 문서

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Public API](../reference/public-api.md)
