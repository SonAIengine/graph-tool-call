---
title: OpenAPI Ingestion
description: Convert Swagger or OpenAPI sources into normalized graph-tool-call tool schemas.
---

# OpenAPI Ingestion

OpenAPI ingestion converts Swagger 2.0 and OpenAPI 3.x sources into normalized
`ToolSchema` objects. Each HTTP operation becomes a searchable tool with method,
path, operation id, summary, parameters, schemas, security hints, semantic
metadata, and IO contracts.

This page covers the engine-level ingestion path. Product concerns such as DB
rows, user sessions, auth profiles, cookies, and HTTP execution belong in the
adapter.

## When To Use This

Use OpenAPI ingestion when:

- your tool catalog starts from a Swagger UI URL or direct JSON/YAML spec
- one API collection may contain hundreds or thousands of operations
- operation descriptions are noisy and need deterministic metadata
- you need request/response contracts for planning and execution
- you want a stored artifact that can be inspected and validated later

Do not use ingestion to attach live credentials. Runtime auth should be resolved
only when the adapter executes a plan.

## Source Types

| Source | Supported Shape | Notes |
| --- | --- | --- |
| Direct file | `openapi.json`, `swagger.yaml` | Best for reproducible local tests |
| Direct URL | `https://.../openapi.json` | Remote fetch obeys URL safety options |
| Swagger UI URL | `https://.../swagger-ui/index.html` | The engine discovers the backing spec URL |
| Python dict | already-loaded spec | Useful in tests and product adapters |
| Sequence | multiple specs | Used by collection artifact builders |

Private or internal URLs are blocked by default. Pass `allow_private_hosts=True`
only from trusted infrastructure.

## Minimal Flow

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

for tool in graph.retrieve("find pets by status", top_k=5):
    print(tool.name, tool.description)
```

## Build A Collection Artifact

Use `build_openapi_collection_artifact()` when the result must be stored by a
product adapter or inspected by a UI.

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchType"},
)

print(artifact["metadata"]["tool_count"])
print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

## Artifact Options

| Option | Default | Purpose |
| --- | --- | --- |
| `required_only` | `False` | Keep only required schema fields during ingest |
| `skip_deprecated` | `True` | Skip deprecated OpenAPI operations |
| `allow_private_hosts` | `False` | Permit private/internal URL fetches |
| `max_response_bytes` | `5_000_000` | Limit remote spec size |
| `promote_contract_signals` | `True` | Promote request/response fields into graph evidence |
| `max_contract_producers_per_field` | `3` | Cap producer expansion per field |
| `derive_semantic_metadata` | `True` | Derive action/resource/module/result-shape metadata |
| `overwrite_ai_metadata` | `False` | Preserve manually curated metadata by default |
| `context_field_names` | `None` | Adapter-provided generic context field names |
| `auth_field_names` | `None` | Adapter-provided auth field names |
| `paging_field_names` | `None` | Adapter-provided paging field names |
| `search_filter_field_names` | `None` | Adapter-provided search/filter field names |
| `metadata` | `None` | Product-neutral metadata to attach to the artifact |

Product-specific aliases should be passed as options. Do not hard-code product
terms in the engine.

## Output Shape

The collection artifact keeps the normal graph save shape and adds
product-facing build facts.

| Section | Purpose |
| --- | --- |
| `graph` | Serialized NetworkX-style graph |
| `tools` | Normalized tool schemas |
| `metadata` | build version, source, options, and collection graph version |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | data-flow, structural, manual, trace, and evidence counts |
| `readiness_report` | deterministic readiness diagnostics |
| `source_snapshot_manifest` | source identity and hash information |
| `ingest_summary` | operation and duplicate handling summary |

## Stable OpenAPI Metadata

OpenAPI-derived tools may include:

| Field | Purpose |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | Operation path |
| `metadata.openapi.operation_id` | Stable operation identifier when available |
| `metadata.openapi.parameters` | Query, path, header, and cookie parameters |
| `metadata.openapi.security` | OpenAPI security hints |
| `metadata.request_body_schema` | Request body schema summary |
| `metadata.response_schema` | Response schema summary |
| `metadata.api_contract` | Engine-level consumes, produces, and links |
| `metadata.ai_metadata` | Deterministic semantic action/resource/module fields |

## Diagnostics

After ingestion, inspect these sections before enabling execution:

```python
summary = artifact["readiness_report"]["summary"]
semantic = artifact["semantic_summary"]
edges = artifact["edge_quality_summary"]

print(summary["status"], summary["readiness_score"])
print(semantic["canonical_action_known_rate"])
print(edges["strong_deterministic_evidence_count"])
```

Important signals:

- missing request or response schemas
- low semantic action/resource coverage
- weak edge evidence
- auth required but not represented in adapter readiness
- one module containing too many unrelated tools

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| No tools produced | Spec URL is wrong or Swagger UI discovery failed | Use a direct spec URL or allow trusted private hosts |
| Missing response contracts | OpenAPI responses have no schema or use unsupported content | Repair the spec or add adapter-side contract repair |
| Too many `unknown` actions | Operation ids and summaries are weak | Add generic aliases or curated semantic metadata |
| No producer expansion | Response fields were not extracted | Check `metadata.api_contract.produces` |
| Auth appears as normal data | Auth field names are product-specific | Pass `auth_field_names` from the adapter |

## Related Pages

- [IO Contracts](./io-contracts.md)
- [Semantic Build](./semantic-build.md)
- [Readiness Diagnostics](./readiness-diagnostics.md)
- [Collection Artifacts](./collection-artifacts.md)
