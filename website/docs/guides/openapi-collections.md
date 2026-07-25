---
title: OpenAPI Collections
description: Build large OpenAPI surfaces into searchable, plannable, executable tool graph artifacts.
---

# OpenAPI Collections

Use OpenAPI collections when an agent needs to search and operate over a large
API surface.

An OpenAPI collection should be treated as a build artifact, not just a list of
HTTP endpoints. The useful artifact contains tools, contracts, semantic
metadata, graph edges, readiness diagnostics, and validation results.

## Recommended Build Pipeline

1. Load the OpenAPI source.
2. Extract operation contracts.
3. Derive semantic action/resource/module metadata.
4. Build graph edges from structure, contracts, and curated evidence.
5. Generate a readiness report.
6. Run search and planning quality cases before enabling execution.

## Minimal Build

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

Persist the artifact in application storage and preserve unknown fields during
source refresh or rebuild.

## Artifact Sections

| Section | Purpose |
| --- | --- |
| `tools` | normalized operation tool schemas |
| `edges` | structural, contract, semantic, manual, or trace graph edges |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | evidence distribution for graph edges |
| `readiness_report` | deterministic OpenAPI readiness diagnostics |
| `metadata` | version and build context |

## Readiness Report

`analyze_openapi_collection()` reports whether a collection is ready for search,
planning, and execution.

Stable issue codes include:

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

## Contract Index

Use `extract_openapi_contract_index()` when an adapter needs operation-level
facts without depending on internal OpenAPI parser helpers.

```python
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")
for operation in index["operations"]:
    print(operation["method"], operation["path"], operation["operationId"])
```

## Adapter Responsibilities

The engine builds product-neutral evidence. The application owns:

- DB rows and collection lifecycle
- auth profile and runtime session headers
- UI for readiness, graph, and Quality Lab results
- safe execution policy
- manual operator overrides
- preserving `quality_lab`, `trace_edges`, and `learning` metadata on rebuild

## Promotion To Execution

Do not enable execution only because ingestion succeeded. Require:

- readiness report without blocker issues
- search Quality Lab suite passing
- target selector diagnostics visible
- plan cases passing for representative workflows
- auth readiness configured
- mutation safety policy for write APIs

## Related Pages

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Quality Lab](../validation/quality-lab.md)
