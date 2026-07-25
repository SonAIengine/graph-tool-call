---
title: XGEN 통합
description: graph-tool-call을 XGEN API Collection build, retrieval, Planflow, execution, Quality Lab, trace learning에 연결하는 기준입니다.
---

# XGEN 통합

XGEN은 `graph-tool-call`을 product-neutral engine으로 다루는 것이 좋습니다.

## 경계

`graph-tool-call`이 담당합니다.

- OpenAPI ingest와 contract extraction
- semantic metadata
- graph edge normalization과 evidence
- retrieval과 target selection
- plan synthesis diagnostics
- scrub된 trace learning record

XGEN이 담당합니다.

- DB 저장
- auth profile과 user/session context
- API collection UX
- SSE/log forwarding
- 실제 HTTP 실행 정책
- provider/model 선택

이 경계가 중요합니다. product-specific DB/auth/session/SSE logic은 library로 옮기지
않고, generic contract/search/selector logic은 XGEN에 중복 구현하지 않습니다.

## API Collection Build

API collection을 build할 때 XGEN은 다음을 저장하는 것이 좋습니다.

- `graph_tool_call_version`
- `collection_graph_version`
- `semantic_summary`
- `edge_quality_summary`
- `readiness_report`
- operation `metadata.openapi`
- operation `metadata.api_contract`

## Build Flow

```text
OpenAPI source
  -> graph-tool-call contract index
  -> semantic metadata
  -> collection artifact
  -> readiness report
  -> Quality Lab search/plan cases
  -> auth/readiness gate 통과 후 execution enabled
```

rebuild 중에는 다음을 보존합니다.

- manual `ai_metadata`
- `context_defaults`
- `enum_mappings`
- Quality Lab case와 last result
- manual/promoted trace edge
- learning suggestion과 promotion status

## Runtime

Runtime에서는 다음 순서를 권장합니다.

1. evidence와 함께 candidate를 retrieve합니다.
2. selector-ranked candidate를 LLM에 넘깁니다.
3. `select_target_candidate`로 LLM target을 guard합니다.
4. plan을 합성합니다.
5. auth readiness를 preflight합니다.
6. 실행하고 scrub된 trace evidence를 저장합니다.

## LLM Provider 역할

XGEN의 LLM provider/model은 compact하고 selector-ranked된 catalog를 받아야 합니다.
collection이 충분히 작지 않다면 전체 API collection을 provider에 넘기지 않습니다.

LLM은 intent interpretation과 final response generation을 담당합니다. deterministic
retrieval evidence, target guardrail, plan diagnostic, learning suggestion은 engine이
담당합니다.

## Quality Lab 역할

Quality Lab은 collection 변경의 operational gate가 되어야 합니다.

| Mode | 목적 |
| --- | --- |
| `search` | expected target이 Top-K에 있는지 |
| `plan` | target 선택과 plan synthesis가 가능한지 |
| `execute` | adapter auth와 downstream API path가 안전하게 동작하는지 |

execute mode는 `auth_context_required`, `auth_profile_missing`,
`auth_header_resolution_failed`, `auth_failed`, `http_4xx`, `http_5xx`를 구분해야 합니다.

## UI Requirements

XGEN은 비엔지니어도 collection 상태를 이해할 수 있게 다음을 보여줘야 합니다.

- readiness score와 top issue code
- semantic coverage
- edge quality summary
- Quality Lab case와 last run result
- target selector diagnostic
- auth readiness state
- shadow/promoted/rejected 상태의 learning suggestion

대형 graph는 먼저 map mode로 열고, 사용자가 module/resource/target/workflow를 고른 뒤
scoped graph mode로 들어가야 합니다.

## 관련 문서

- [OpenAPI Collections](./openapi-collections.md)
- [XGEN Quality Lab](../integrations/xgen-quality-lab.md)
- [Auth Readiness](../build/auth-readiness.md)
