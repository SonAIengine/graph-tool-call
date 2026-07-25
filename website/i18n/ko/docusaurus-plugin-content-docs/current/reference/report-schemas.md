---
title: Report Schema
description: readiness, graph quality, diagnostic report의 안정 field입니다.
---

# Report Schema

Report는 deterministic diagnostic입니다. 제품 metadata에 저장하거나,
collection UI에 표시하거나, regression gate로 사용할 수 있습니다. 같은 spec과
option이면 같은 report가 나와야 합니다.

## OpenAPI collection report

`analyze_openapi_collection()`과 `ToolGraph.analyze_openapi()`는 다음 shape의
`OpenAPICollectionReport`를 반환합니다.

```json
{
  "summary": {},
  "coverage": {},
  "graph_readiness": {},
  "issues": [],
  "recommendations": []
}
```

## Summary

| Field | 의미 |
| --- | --- |
| `tool_count` | ingested tool 수 |
| `operation_count` | 반영된 OpenAPI operation 수 |
| `unique_tool_count` | duplicate 처리 후 tool 수 |
| `deprecated_tool_count` | deprecated operation 수 |
| `readiness_score` | 0-100 deterministic score |
| `status` | `ready`, `warning`, `blocked` |

점수 정책은 100점에서 시작해 blocker당 15점, warning당 5점을 감점하고
0-100으로 clamp합니다. blocker가 있으면 `blocked`, warning이 있거나 90점
미만이면 `warning`입니다.

## Coverage

| Field | 의미 |
| --- | --- |
| `request_schema_tool_count` | request schema가 있는 tool |
| `response_schema_tool_count` | response schema가 있는 tool |
| `consumes_field_count` | request/path/query/header/body leaf |
| `produces_field_count` | response leaf |
| `auth_field_count` | auth로 분류된 field |
| `context_field_count` | runtime context로 분류된 field |
| `enum_field_count` | enum field |
| `response_envelope_tool_count` | response envelope candidate |
| `semantic_action_known_rate` | action이 unknown이 아닌 비율 |
| `semantic_resource_assigned_rate` | resource가 할당된 비율 |
| `semantic_module_assigned_rate` | path/module이 할당된 비율 |

## Issue

```json
{
  "severity": "warning",
  "code": "missing_response_schema",
  "tool": "getOrderDetail",
  "message": "Operation has no response schema.",
  "evidence": {"method": "GET", "path": "/orders/{orderId}"},
  "recommendation": "Add a 2xx response schema or repair the contract."
}
```

주요 issue code:

| Code | 의미 |
| --- | --- |
| `missing_request_schema` | request schema 누락 |
| `generic_request_body` | request body가 너무 generic |
| `missing_response_schema` | response schema 누락 |
| `duplicate_operation_id` | operationId 중복 |
| `missing_operation_id` | operationId 없음 |
| `auth_required` | OpenAPI상 auth 필요 |
| `unsupported_content_type` | content type 표현 어려움 |
| `response_envelope_detected` | wrapper/body view candidate 감지 |
| `low_graph_connectivity` | producer/consumer 연결성 약함 |
| `no_contract_fields` | consumes/produces field 추출 실패 |
| `semantic_action_unknown_rate_high` | unknown action 비율 높음 |
| `semantic_resource_unassigned_rate_high` | resource 미할당 비율 높음 |
| `weak_edge_evidence` | weak/structural edge 비율 높음 |
| `module_cluster_too_large` | module cluster가 너무 큼 |

## 저장 안전성

Report에는 raw request body, response body, auth header value, cookie, 사용자
식별값을 넣지 않습니다. runtime diagnostic을 추가하더라도 reason code,
header name, scrub된 evidence만 저장하세요.

## 관련 문서

- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Quality Lab](../validation/quality-lab.md)
- [Artifact Schema](./artifact-schemas.md)
