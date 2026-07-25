---
title: Report Schemas
description: Stable report fields for readiness, graph quality, and diagnostics.
---

# Report Schemas

Reports are deterministic diagnostics. They are meant to be stored in product
metadata, shown in collection UIs, and used as regression gates. The same input
spec and options should produce the same report.

## OpenAPI Collection Report

`analyze_openapi_collection()` and `ToolGraph.analyze_openapi()` return an
`OpenAPICollectionReport` with this shape:

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

| Field | Meaning |
| --- | --- |
| `tool_count` | Number of ingested tools |
| `operation_count` | Number of OpenAPI operations represented |
| `unique_tool_count` | Tool count after duplicate handling |
| `deprecated_tool_count` | Deprecated operations found |
| `readiness_score` | Deterministic 0-100 score |
| `status` | `ready`, `warning`, or `blocked` |

Score policy:

- start at 100
- subtract 15 for each blocker issue
- subtract 5 for each warning
- clamp to 0-100
- any blocker makes the status `blocked`
- warnings or score below 90 make the status `warning`

## Coverage

Coverage explains whether tools have the information needed for search,
planning, and execution.

| Field | Meaning |
| --- | --- |
| `request_schema_tool_count` | Tools with request schema information |
| `response_schema_tool_count` | Tools with response schema information |
| `consumes_field_count` | Request/path/query/header/body leaves consumed |
| `produces_field_count` | Response leaves produced |
| `auth_field_count` | Fields classified as auth |
| `context_field_count` | Fields classified as runtime context |
| `enum_field_count` | Enum-bearing fields |
| `response_envelope_tool_count` | Tools with response envelope candidates |
| `semantic_action_known_rate` | Tools with non-unknown action |
| `semantic_resource_assigned_rate` | Tools with assigned resource |
| `semantic_module_assigned_rate` | Tools with assigned path/module |
| `observed_contract_coverage` | Contract coverage inferred from tool metadata |

## Graph Readiness

| Field | Meaning |
| --- | --- |
| `graph_available` | A graph was available during analysis |
| `edge_count` | Total graph edges |
| `relation_counts` | Edge counts by relation |
| `producer_edge_count` | Data-flow producer edges |
| `producer_consumer_candidate_count` | Fields that could connect producers to consumers |
| `orphan_tool_count` | Tools with no useful graph connection |
| `isolated_tool_count` | Tools with no in/out edges |
| `edge_quality_summary` | Evidence quality counts |

## Issues

Each issue is stable enough for product UI labels and test assertions.

```json
{
  "severity": "warning",
  "code": "missing_response_schema",
  "tool": "getOrderDetail",
  "message": "Operation has no response schema.",
  "evidence": {"method": "GET", "path": "/orders/{orderId}"},
  "recommendation": "Add a 2xx response schema or repair the contract from source metadata."
}
```

Common issue codes:

| Code | Meaning |
| --- | --- |
| `missing_request_schema` | Request schema is missing where expected |
| `generic_request_body` | Request body is too generic for planning |
| `missing_response_schema` | Response schema is missing |
| `duplicate_operation_id` | Multiple operations use the same operationId |
| `missing_operation_id` | Operation has no operationId |
| `auth_required` | OpenAPI indicates auth is required |
| `unsupported_content_type` | Content type cannot be represented cleanly |
| `array_leaf_alignment_required` | Nested array/object leaves need alignment |
| `response_envelope_detected` | Response wrapper/body view candidate detected |
| `low_graph_connectivity` | Graph has weak producer/consumer connectivity |
| `no_contract_fields` | No consumes/produces contract fields were extracted |
| `semantic_action_unknown_rate_high` | Too many tools have unknown action |
| `semantic_resource_unassigned_rate_high` | Too many tools lack primary resource |
| `weak_edge_evidence` | Too many edges are weak or structural-only |
| `module_cluster_too_large` | A module cluster is too broad to inspect directly |

## Recommendations

Recommendations are derived from issue codes. They should be displayed as
operator actions, not as hidden logs.

Examples:

- add or repair missing response schemas
- provide adapter-specific context/auth field names
- add resource/action aliases for ambiguous naming conventions
- split overly large source/module clusters
- keep execute disabled until auth readiness is configured

## Safe Storage

Reports should not contain raw request bodies, response bodies, auth header
values, cookies, or user identifiers. If a product adds runtime diagnostics,
store only reason codes, header names, and scrubbed evidence.

## Related Pages

- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Quality Lab](../validation/quality-lab.md)
- [Artifact Schemas](./artifact-schemas.md)
