# OpenAPI Readiness Report

`graph-tool-call` can inspect an OpenAPI collection before it is used as a tool
graph. The report answers a narrow question: is this collection ready for graph
search, target selection, Planflow synthesis, and HTTP execution adapters?

The report is deterministic. It does not call an LLM, does not execute API
requests, and does not read runtime credentials. It only summarizes facts
already preserved during OpenAPI ingest.

## Public API

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection(
    "openapi.json",
    context_field_names={"siteNo", "tenantId"},
    paging_field_names={"pageNo", "pageSize"},
    search_filter_field_names={"keyword", "searchWord"},
)
payload = report.to_dict()
```

Already-ingested graphs can use:

```python
report = tg.analyze_openapi(context_field_names={"siteNo"})
```

When the graph was loaded from storage and no longer contains the full
`metadata.openapi` block, the report falls back to persisted OpenAPI-like
metadata and `metadata.api_contract`. This keeps operation counts,
consumes/produces coverage, response schema coverage, and context/auth
classification stable for stored XGEN API Collection graphs.

The CLI exposes the same report:

```bash
graph-tool-call inspect-openapi openapi.json
graph-tool-call inspect-openapi openapi.json --json
```

Remote URLs use the same private-host safety default as OpenAPI ingest; pass
`--allow-private-hosts` only when inspecting an internal API from a trusted
environment.

## Report Schema

- `summary`: `tool_count`, `operation_count`, `unique_tool_count`,
  `unique_operation_count`, `deprecated_tool_count`, `readiness_score`, and
  `status`.
- `coverage`: request-body coverage, request/response schema coverage,
  consumes/produces field counts, auth/context/enum fields, example-inferred
  fields, response envelopes, body-view candidates, and OpenAPI link count.
- `graph_readiness`: edge count, relation counts, producer-edge count, isolated
  tools, producer/consumer field candidates, and whether graph data was
  available.
- `issues`: stable rows with `severity`, `code`, `tool`, `message`, `evidence`,
  and `recommendation`.
- `recommendations`: de-duplicated actions in issue order.

## Score Policy

Scoring is deliberately simple and reproducible:

- Start at 100.
- Each `blocker` issue subtracts 15.
- Each `warning` issue subtracts 5.
- `info` issues do not affect the score.
- Clamp to 0-100.
- Any blocker makes the report `blocked`.
- Warnings or a score below 90 make the report `warning`.
- Otherwise the report is `ready`.

`ready` means the static contract is usable for the next smoke test. It is not
a guarantee that runtime credentials, business permissions, or live server
state are valid.

## Stable Issue Codes

- `missing_request_schema`: a required body declares content but has no schema.
- `generic_request_body`: a body schema is only a generic object.
- `missing_response_schema`: no success response schema, fields, or headers were
  extracted for a body-capable success status.
- `duplicate_operation_id`: duplicate operation IDs forced deterministic tool
  name deduplication.
- `missing_operation_id`: operation ID was generated from method and path.
- `auth_required`: OpenAPI security is required at runtime.
- `unsupported_content_type`: request media type is outside the built-in
  executor renderers.
- `array_leaf_alignment_required`: request body uses array leaf paths and needs
  row-wise validation/resume diagnostics.
- `response_envelope_detected`: response wrapper metadata should be preserved
  through runtime result forwarding.
- `low_graph_connectivity`: contract fields suggest producer/consumer pairs,
  but the graph has no data-flow edges.
- `no_contract_fields`: no request, response, auth, or link contract fields were
  extracted for a tool.

## XGEN Usage

XGEN should run this report after API Collection registration and again after
graph rebuild. The library report should be stored or forwarded as-is; DB,
auth, user ID, SSE, and UI decisions stay in XGEN.

Recommended XGEN behavior:

- Block or warn before enabling Planflow when `status` is `blocked`.
- Show issue code, tool, evidence, and recommendation in the collection detail
  screen.
- Pass XGEN-specific context fields such as site/tenant/user/page names through
  options.
- Preserve `response_envelope_detected` and `array_leaf_alignment_required`
  metadata in SSE/logs so popup/resume flows can explain missing inputs.
