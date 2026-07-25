---
title: XGEN Quality Lab
description: XGEN Quality Lab을 collection validation을 위한 product adapter로 사용합니다.
---

# XGEN Quality Lab

XGEN Quality Lab은 collection-specific validation case를 저장하고 실행합니다.
graph-tool-call은 engine decision을 맡고, XGEN은 DB, auth, session, HTTP
execution, SSE, UI를 맡습니다.

## Responsibilities

graph-tool-call 제공:

- retrieval results
- selector diagnostics
- plan diagnostics
- runner event schemas
- learning suggestions

XGEN 제공:

- collection storage
- auth profile resolution
- user session context
- HTTP execution
- result persistence
- operator UI

## 관련 문서

- [Quality Lab](../validation/quality-lab.md)
- [XGEN API Collection](../guides/xgen-integration.md)
