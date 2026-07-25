---
title: Collection Artifacts
description: Build portable OpenAPI collection artifacts with graph metadata, readiness reports, and quality summaries.
---

# Collection Artifacts

A collection artifact is a portable JSON representation of an API collection. It
lets product adapters store the graph once and reuse it for retrieval, target
selection, planning, validation, and UI inspection.

Treat the artifact as the boundary between the product and the engine. The
engine produces product-neutral evidence; the adapter decides where to store it,
how to authorize execution, and how to present diagnostics.

## Minimal Example

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact("openapi.json")
print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

## Build With Adapter Options

```python
artifact = build_openapi_collection_artifact(
    ["orders.openapi.json", "members.openapi.json"],
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    metadata={"collection_id": "commerce-readonly"},
    context_field_names={"tenantId", "siteNo"},
    paging_field_names={"page", "size", "limit"},
    search_filter_field_names={"keyword", "searchText"},
)
```

Aliases should be generic and adapter-provided. The library should not contain
one customer's private field dictionary.

## Important Sections

| Section | Purpose |
| --- | --- |
| `tools` | Normalized tool schemas |
| `edges` | Structural, contract, manual, and trace-derived relationships |
| `semantic_summary` | Action/resource/module coverage |
| `edge_quality_summary` | Data-flow and evidence quality counts |
| `readiness_report` | Deterministic build and execution readiness diagnostics |
| `quality_lab` | Optional product-side validation cases and results |
| `learning` | Optional scrubbed trace learning attempts and suggestions |

## Version And Provenance

Persist enough build metadata to reproduce an artifact:

```json
{
  "metadata": {
    "graph_tool_call_version": "0.32.1",
    "collection_graph_version": 2,
    "source_count": 2,
    "tool_count": 624,
    "build_options": {
      "derive_semantic_metadata": true,
      "promote_contract_signals": true
    }
  }
}
```

Do not overwrite manual fields during rebuild unless the operator explicitly
requests it. Preserving metadata is what makes the artifact safe for product use.

## Adapter Notes

Adapters should preserve operator edits such as `ai_metadata`,
`context_defaults`, `enum_mappings`, manual edges, quality cases, and promoted
learning suggestions during rebuilds.

## Rebuild Policy

When a source changes:

1. Fetch or load the new source.
2. Build a new engine artifact.
3. Merge preserved product-owned fields.
4. Re-run readiness and quality gates.
5. Promote the artifact only when blockers are resolved.

The merge step should preserve:

- manually curated `ai_metadata`
- `context_defaults`
- `enum_mappings`
- manual and promoted trace edges
- `quality_lab.cases` and last result summaries
- `learning.suggestions` with status

## UI Checklist

A collection details screen should show:

- tool and edge counts
- semantic coverage
- edge quality summary
- readiness status and top issues
- source version/provenance
- last Quality Lab result
- whether execution is blocked by auth or readiness

Graph visualization should prefer summarized clusters for large collections and
only render dense edges after the user scopes down to a module, resource, or
target workflow.

## Validation

Use collection artifact tests when changing build options or stored schema:

```bash
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## Related Pages

- [Readiness Diagnostics](./readiness-diagnostics.md)
- [OpenAPI Collections](../guides/openapi-collections.md)
- [XGEN API Collection](../guides/xgen-integration.md)
