---
title: XGEN Quality Lab
description: XGEN Quality Lab을 collection validation을 위한 product adapter로 사용합니다.
---

# XGEN Quality Lab

XGEN Quality Lab은 collection-specific validation case를 저장하고 실행합니다.
graph-tool-call은 engine decision을 맡고, XGEN은 DB, auth, session, HTTP
execution, SSE, UI를 맡습니다.

collection owner가 API collection을 Planflow 경로로 열기 전에 search, plan, execute를
안전하게 검증해야 할 때 이 integration을 사용합니다.

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

## Data Flow

```text
Quality Lab case
  -> graph-tool-call retrieval
  -> target selector diagnostics
  -> plan synthesis
  -> optional PlanRunner execution through XGEN adapter
  -> result, failure reason, learning suggestion
```

Search와 plan mode는 자주 실행할 수 있어야 합니다. Execute mode는 auth readiness,
host allowlist, mutation safety, cleanup policy를 이해한 경우에만 실행합니다.

## Case Modes

| Mode | XGEN이 graph-tool-call에 맡기는 것 | XGEN이 소유하는 것 |
| --- | --- | --- |
| `search` | retrieval result와 evidence | case storage와 UI display |
| `plan` | target selector, plan synthesis, user input slot | provided entities와 result persistence |
| `execute` | runner event schema와 trace learning record | auth, HTTP execution, mutation safety, cleanup |

## Auth Boundary

graph-tool-call은 tool 또는 collection이 auth를 요구한다는 진단을 낼 수 있습니다.
하지만 execution header는 XGEN이 현재 user session 또는 collection auth profile에서
resolve해야 합니다. Quality Lab result에는 header name과 reason code만 저장하고 raw
token/cookie value는 저장하지 않습니다.

대표 reason:

| Reason | 의미 |
| --- | --- |
| `auth_context_required` | usable runtime session context 없음 |
| `auth_profile_missing` | collection이 auth를 요구하지만 profile 없음 |
| `auth_header_resolution_failed` | XGEN이 execution header를 만들지 못함 |
| `auth_failed` | downstream API가 401 또는 403 반환 |

## Result Review

운영자가 볼 수 있어야 하는 것:

- query와 case mode
- Top-K hit position
- LLM target과 selected target
- selector override와 reason code
- plan steps와 user input slots
- auth readiness
- runner events와 failed stage
- 생성되거나 shadow-applied된 learning suggestion

## Promotion Policy

Quality Lab에서 나온 learning evidence도 live execution과 같은 observe/shadow/promote
정책을 따라야 합니다. 성공한 execute case는 suggestion을 만들 수 있지만, ranking에
영향을 주려면 반복 성공, operator approval, explicit promotion gate가 필요합니다.

## 관련 문서

- [Quality Lab](../validation/quality-lab.md)
- [XGEN API Collection](../guides/xgen-integration.md)
- [Auth Readiness](../build/auth-readiness.md)
- [Trace Learning](../concepts/trace-learning.md)
