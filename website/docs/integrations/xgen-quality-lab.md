---
title: XGEN Quality Lab
description: Use XGEN Quality Lab as the product adapter for collection validation.
---

# XGEN Quality Lab

XGEN Quality Lab stores and runs collection-specific validation cases. It uses
graph-tool-call for engine decisions and XGEN for DB, auth, session, HTTP
execution, SSE, and UI.

## Responsibilities

graph-tool-call provides:

- retrieval results
- selector diagnostics
- plan diagnostics
- runner event schemas
- learning suggestions

XGEN provides:

- collection storage
- auth profile resolution
- user session context
- HTTP execution
- result persistence
- operator UI

## Related Pages

- [Quality Lab](../validation/quality-lab.md)
- [XGEN API Collection](../guides/xgen-integration.md)
