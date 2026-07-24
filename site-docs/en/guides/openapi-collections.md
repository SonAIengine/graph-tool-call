# OpenAPI Collections

Use OpenAPI collections when an agent needs to search and operate over a large
API surface.

## Recommended Build Pipeline

1. Load the OpenAPI source.
2. Extract operation contracts.
3. Derive semantic action/resource/module metadata.
4. Build graph edges from structure, contracts, and curated evidence.
5. Generate a readiness report.
6. Run search and planning quality cases before enabling execution.

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

