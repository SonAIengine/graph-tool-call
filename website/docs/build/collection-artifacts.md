---
title: Collection Artifacts
description: Build portable OpenAPI collection artifacts with graph metadata, readiness reports, and quality summaries.
---

# Collection Artifacts

A collection artifact is a portable JSON representation of an API collection. It
lets product adapters store the graph once and reuse it for retrieval, target
selection, planning, validation, and UI inspection.

## Minimal Example

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact("openapi.json")
print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

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

## Adapter Notes

Adapters should preserve operator edits such as `ai_metadata`,
`context_defaults`, `enum_mappings`, manual edges, quality cases, and promoted
learning suggestions during rebuilds.

## Related Pages

- [Readiness Diagnostics](./readiness-diagnostics.md)
- [XGEN API Collection](../guides/xgen-integration.md)
