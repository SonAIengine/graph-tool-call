---
title: Artifact Schemas
description: Stable collection artifact sections used by adapters and UI tools.
---

# Artifact Schemas

Collection artifacts store the graph and the evidence needed to reuse it.

## Top-Level Sections

| Section | Purpose |
| --- | --- |
| `tools` | Normalized tool schemas |
| `edges` | Graph relationships |
| `metadata` | Version and source metadata |
| `semantic_summary` | Semantic build quality |
| `edge_quality_summary` | Edge evidence counts |
| `readiness_report` | Deterministic readiness diagnostics |
| `quality_lab` | Optional validation cases and results |
| `learning` | Optional trace learning data |

## Related Pages

- [Collection Artifacts](../build/collection-artifacts.md)
- [Compatibility](./compatibility.md)
