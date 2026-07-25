---
title: Readiness Diagnostics
description: Diagnose whether an API collection is ready for search, planning, and execution.
---

# Readiness Diagnostics

Readiness diagnostics provide deterministic feedback when an API collection is
not yet useful for tool graph search or Planflow execution.

Use this report immediately after OpenAPI ingest and again after source refresh.
It is intentionally LLM-free: the same spec and options should produce the same
status, score, issue codes, and recommendations.

## Public API

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection("openapi.json")
print(report.summary.readiness_score)
print(report.summary.status)
```

For an already-built graph, call the convenience method without re-ingesting the
source:

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
report = graph.analyze_openapi()
```

## Report Shape

| Section | What It Answers |
| --- | --- |
| `summary` | How many tools exist, how many are duplicated or deprecated, and the final readiness score |
| `coverage` | Whether request/response schemas, contract fields, enums, auth fields, and envelope candidates were detected |
| `graph_readiness` | Whether operations are connected by useful evidence or isolated |
| `issues` | Stable issue records with severity, code, tool, evidence, and recommendation |
| `recommendations` | The next repair actions before enabling plan or execute |

The report is meant to be stored in a product artifact, shown in a UI, and
attached to quality gate output.

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

## Issue Record

Each issue should be treated as a diagnostic record, not just a log message.

```json
{
  "severity": "warning",
  "code": "missing_response_schema",
  "tool": "getOrderList",
  "message": "No usable response schema was found.",
  "evidence": {"method": "GET", "path": "/orders"},
  "recommendation": "Add a response schema or repair the source contract."
}
```

Product adapters should preserve unknown fields so newer engine versions can add
diagnostics without breaking older stored reports.

## Status Policy

The report should classify a collection as:

- `ready` when the score is high and no blocker exists
- `warning` when the collection can be used but has known weaknesses
- `blocked` when search, planning, or execution would be misleading

The default score policy starts at 100, subtracts for blocker and warning
issues, then clamps to `0..100`. A blocker should force `blocked` even if the
numeric score looks acceptable.

## How To Interpret It

| Signal | Meaning | Typical Action |
| --- | --- | --- |
| low response coverage | retrieval can find tools, but plan/execution may not know result fields | repair response schemas or add contract metadata |
| high semantic unknown rate | search and selector have weak action/resource signals | pass generic aliases or curate metadata |
| low graph connectivity | candidate expansion cannot find producers/consumers | inspect contract fields and edge evidence |
| auth required | execution needs adapter-side auth profile/session handling | configure auth readiness before live execution |
| envelope candidates | response data may be nested under `data`, `result`, or similar wrappers | verify body view extraction before planning |

## Adapter Pattern

```python
report = analyze_openapi_collection(
    source,
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchType"},
)

if report.summary.status == "blocked":
    disable_execute_for_collection()
else:
    save_report(report.to_dict())
```

Use adapter-provided field dictionaries for product naming conventions. Keep the
engine generic; do not hard-code one product's `mallNo` or `siteNo` names in the
library.

## Validation

Run the readiness tests when OpenAPI parsing, semantic build, or edge quality
logic changes:

```bash
poetry run pytest tests/test_openapi_readiness.py -q
```

For documentation builds, make sure issue code terms are still searchable:

```bash
cd website
npm run build
```

## Related Pages

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Collection Artifacts](./collection-artifacts.md)
- [Auth Readiness](./auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
