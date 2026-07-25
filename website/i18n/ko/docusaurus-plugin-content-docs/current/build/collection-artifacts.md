---
title: Collection Artifacts
description: graph metadata, readiness report, quality summary를 가진 portable OpenAPI collection artifact를 만듭니다.
---

# Collection Artifacts

Collection artifact는 API collection의 portable JSON 표현입니다. product adapter는
graph를 한 번 저장한 뒤 retrieval, target selection, planning, validation, UI
inspection에 재사용할 수 있습니다.

## 최소 예제

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact("openapi.json")
print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

## 중요 Section

| Section | Purpose |
| --- | --- |
| `tools` | normalized tool schema |
| `edges` | structural, contract, manual, trace-derived relationship |
| `semantic_summary` | action/resource/module coverage |
| `edge_quality_summary` | data-flow and evidence quality count |
| `readiness_report` | deterministic readiness diagnostics |
| `quality_lab` | optional validation cases and results |
| `learning` | optional scrubbed trace learning attempts and suggestions |

## Adapter Notes

Adapter는 rebuild 중에도 `ai_metadata`, `context_defaults`, `enum_mappings`,
manual edge, quality case, promoted learning suggestion 같은 운영자 수정을
보존해야 합니다.

## 관련 문서

- [Readiness Diagnostics](./readiness-diagnostics.md)
- [XGEN API Collection](../guides/xgen-integration.md)
