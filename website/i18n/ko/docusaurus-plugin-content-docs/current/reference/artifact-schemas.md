---
title: Artifact Schemas
description: adapter와 UI tool이 사용하는 stable collection artifact section입니다.
---

# Artifact Schemas

Collection artifact는 graph와 재사용에 필요한 evidence를 저장합니다.

## Top-Level Sections

| Section | Purpose |
| --- | --- |
| `tools` | normalized tool schema |
| `edges` | graph relationship |
| `metadata` | version and source metadata |
| `semantic_summary` | semantic build quality |
| `edge_quality_summary` | edge evidence count |
| `readiness_report` | deterministic readiness diagnostics |
| `quality_lab` | optional validation cases and results |
| `learning` | optional trace learning data |

## 관련 문서

- [Collection Artifacts](../build/collection-artifacts.md)
- [Compatibility](./compatibility.md)
