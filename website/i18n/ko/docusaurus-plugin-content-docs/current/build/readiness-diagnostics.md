---
title: Readiness Diagnostics
description: API collection이 search, planning, execution에 준비됐는지 진단합니다.
---

# Readiness Diagnostics

Readiness diagnostics는 API collection이 tool graph search나 Planflow execution에
아직 적합하지 않을 때 deterministic한 피드백을 제공합니다.

## Public API

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection("openapi.json")
print(report.summary.readiness_score)
print(report.summary.status)
```

## Stable Issue Codes

- `missing_request_schema`
- `generic_request_body`
- `missing_response_schema`
- `duplicate_operation_id`
- `missing_operation_id`
- `auth_required`
- `unsupported_content_type`
- `array_leaf_alignment_required`
- `response_envelope_detected`
- `low_graph_connectivity`
- `no_contract_fields`
- `semantic_action_unknown_rate_high`
- `semantic_resource_unassigned_rate_high`
- `weak_edge_evidence`
- `module_cluster_too_large`

## Status Policy

- `ready`: score가 높고 blocker가 없음
- `warning`: 사용할 수 있지만 알려진 약점이 있음
- `blocked`: search, planning, execution 결과가 오해를 만들 수 있음

## 관련 문서

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Quality Lab](../validation/quality-lab.md)
