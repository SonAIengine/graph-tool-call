---
title: Artifact Schemas
description: Stable collection artifact sections used by adapters and UI tools.
---

# Artifact Schemas

Collection artifacts are JSON-serializable payloads that store a built tool
catalog. They are meant for product adapters that need to persist a graph,
display diagnostics, search without rebuilding, and preserve manual operator
metadata across rebuilds.

## Top-Level Shape

```json
{
  "format_version": "1",
  "library_version": "0.32.1",
  "metadata": {},
  "graph": {},
  "tools": {},
  "readiness_report": {},
  "source_snapshot_manifest": [],
  "ingest_summary": {},
  "edge_stats": {},
  "semantic_summary": {},
  "edge_quality_summary": {}
}
```

The artifact remains compatible with `ToolGraph.load()` because the normal graph
payload is still present. Additional fields are additive diagnostics for
adapters and UIs.

## Sections

| Section | Purpose |
| --- | --- |
| `metadata` | Build time, source identity, build options, summary copies |
| `graph` | Serialized graph nodes and edges |
| `tools` | Normalized `ToolSchema` rows keyed by tool name |
| `readiness_report` | Deterministic OpenAPI readiness report |
| `source_snapshot_manifest` | Source labels, URLs, hashes, and operation counts |
| `ingest_summary` | Duplicate handling and operation counts |
| `edge_stats` | Raw graphify edge extraction stats |
| `semantic_summary` | Action/resource/module/result-shape coverage |
| `edge_quality_summary` | Data-flow, structural, manual, trace, and evidence counts |

Product adapters may add fields such as `quality_lab` or `learning`. They should
preserve unknown fields when repairing contracts or rebuilding the graph.

## Metadata

```json
{
  "built_at": "2026-07-25T00:00:00+00:00",
  "tool_count": 1105,
  "source_count": 1,
  "source_url": "https://example.com/swagger-ui/index.html",
  "spec_urls": ["https://example.com/v3/api-docs"],
  "readiness_summary": {"status": "warning", "readiness_score": 86},
  "build_options": {
    "derive_semantic_metadata": true,
    "promote_contract_signals": true,
    "context_field_names": ["mallNo", "siteNo"]
  }
}
```

Store product-neutral source facts here. Do not store raw auth tokens, cookies,
session ids, or user identifiers.

## Tool Row Metadata

OpenAPI-derived tools commonly include:

| Field | Meaning |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | OpenAPI operation path |
| `metadata.openapi.operation_id` | Operation id when available |
| `metadata.openapi.parameters` | Path/query/header/cookie parameters |
| `metadata.openapi.security` | OpenAPI security requirements |
| `metadata.openapi.path_module` | Deterministic module/path cluster |
| `metadata.request_body_schema` | Request body schema summary |
| `metadata.response_schema` | Response schema summary |
| `metadata.content_types` | Supported request/response content types |
| `metadata.api_contract` | Consumes, produces, links, and contract evidence |
| `metadata.ai_metadata` | Deterministic semantic metadata used by search |

`ai_metadata` may contain `canonical_action`, `primary_resource`,
`one_line_summary`, `when_to_use`, `result_shape`, `semantic_confidence`, and
`semantic_evidence`.

## Graph Edges

Edges should carry enough evidence to explain why two tools are related.

```json
{
  "source": "searchOrders",
  "target": "getOrderDetail",
  "kind": "data_flow",
  "confidence": "extracted",
  "conf_score": 0.92,
  "evidence": "produces orderId consumed by getOrderDetail",
  "evidence_sources": ["api_contract"],
  "data_flow": {"field": "orderId"},
  "is_manual": false
}
```

Adapters may merge manual, LLM-curated, OpenAPI link, and run-observed edges
through `normalize_graph_edge()` and `merge_graph_edges()`.

## Optional Product Fields

The engine does not require these fields, but product integrations commonly
store them with the artifact:

| Field | Purpose |
| --- | --- |
| `quality_lab.cases` | Search, plan, and execute validation cases |
| `quality_lab.results` | Last run results and failure reasons |
| `learning.attempts` | Scrubbed recent execution attempts |
| `learning.suggestions` | Suggested or promoted trace-learning evidence |
| `trace_edges` | Backward-compatible run-observed edge list |

## Compatibility Rules

- Add new fields instead of changing existing field names.
- Preserve unknown fields during rebuilds.
- Keep `collection_graph_version` additive and readable by older adapters where
  possible.
- Store raw payloads only outside the artifact, behind product security controls.
- Scrub any value that looks like a token, cookie, API key, email, phone number,
  or user identifier before saving learning or trace evidence.

## Related Pages

- [Collection Artifacts](../build/collection-artifacts.md)
- [Report Schemas](./report-schemas.md)
- [Event Schemas](./event-schemas.md)
- [Compatibility](./compatibility.md)
