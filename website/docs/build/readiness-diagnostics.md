---
title: Readiness Diagnostics
description: Diagnose whether an API collection is ready for search, planning, and execution.
---

# Readiness Diagnostics

Readiness diagnostics provide deterministic feedback when an API collection is
not yet useful for tool graph search or Planflow execution.

## Public API

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection("openapi.json")
print(report.summary.readiness_score)
print(report.summary.status)
```

## Stable Issue Codes

Common issue codes include:

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

The report should classify a collection as:

- `ready` when the score is high and no blocker exists
- `warning` when the collection can be used but has known weaknesses
- `blocked` when search, planning, or execution would be misleading

## Related Pages

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Quality Lab](../validation/quality-lab.md)
