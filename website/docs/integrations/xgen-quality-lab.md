---
title: XGEN Quality Lab
description: Use XGEN Quality Lab as the product adapter for collection validation.
---

# XGEN Quality Lab

XGEN Quality Lab stores and runs collection-specific validation cases. It uses
graph-tool-call for engine decisions and XGEN for DB, auth, session, HTTP
execution, SSE, and UI.

Use this integration when a collection owner needs to prove that a built API
collection can be searched, planned, and executed safely before turning it into
a Planflow path.

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

## Data Flow

```text
Quality Lab case
  -> graph-tool-call retrieval
  -> target selector diagnostics
  -> plan synthesis
  -> optional PlanRunner execution through XGEN adapter
  -> result, failure reason, learning suggestion
```

Search and plan modes should run often. Execute mode should run only when auth
readiness, host allowlist, mutation safety, and cleanup policy are known.

## Case Modes

| Mode | XGEN Uses graph-tool-call For | XGEN Owns |
| --- | --- | --- |
| `search` | retrieval results and evidence | case storage and UI display |
| `plan` | target selector, plan synthesis, user input slots | provided entities and result persistence |
| `execute` | runner event schema and trace learning records | auth, HTTP execution, mutation safety, cleanup |

## Auth Boundary

graph-tool-call can report that a tool or collection requires auth, but XGEN
must resolve execution headers from the current user session or collection auth
profile. Quality Lab results should store header names and reason codes, never
raw token or cookie values.

Common reasons:

| Reason | Meaning |
| --- | --- |
| `auth_context_required` | no usable runtime session context |
| `auth_profile_missing` | collection requires auth but no profile exists |
| `auth_header_resolution_failed` | XGEN could not create execution headers |
| `auth_failed` | downstream API returned 401 or 403 |

## Result Review

An operator should be able to see:

- query and case mode
- Top-K hit position
- LLM target and selected target
- selector override and reason codes
- plan steps and user input slots
- auth readiness
- runner events and failed stage
- learning suggestions created or shadow-applied

## Promotion Policy

Learning evidence from Quality Lab should follow the same observe/shadow/promote
policy as live execution. A successful execute case can create a suggestion, but
only repeated success, operator approval, or an explicit promotion gate should
make it affect ranking.

## Related Pages

- [Quality Lab](../validation/quality-lab.md)
- [XGEN API Collection](../guides/xgen-integration.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
