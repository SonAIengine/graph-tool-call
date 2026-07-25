---
title: Artifact Schema
description: adapter와 UI가 사용하는 collection artifact의 안정 schema입니다.
---

# Artifact Schema

Collection artifact는 build된 tool catalog를 저장하는 JSON payload입니다.
제품 adapter는 이 artifact를 저장해 graph를 재사용하고, readiness/semantic
quality를 UI에 보여주며, rebuild 때 운영자 수동 metadata를 보존합니다.

## Top-level shape

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

정상 graph payload가 그대로 들어있기 때문에 `ToolGraph.load()`도 읽을 수
있습니다. 추가 top-level field는 adapter와 UI를 위한 diagnostic입니다.

## 주요 section

| Section | 용도 |
| --- | --- |
| `metadata` | build time, source identity, build option, summary copy |
| `graph` | serialized graph node/edge |
| `tools` | tool name으로 keying된 normalized `ToolSchema` |
| `readiness_report` | deterministic OpenAPI readiness report |
| `source_snapshot_manifest` | source URL/hash/operation count |
| `ingest_summary` | duplicate 처리와 operation count |
| `edge_stats` | graphify edge extraction stat |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | data-flow, structural, manual, trace evidence count |

제품은 `quality_lab`이나 `learning` 같은 field를 추가할 수 있습니다.
rebuild/repair 시 알 수 없는 field는 보존하세요.

## Tool metadata

OpenAPI tool에는 보통 다음 metadata가 있습니다.

| Field | 의미 |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | OpenAPI operation path |
| `metadata.openapi.operation_id` | operation id |
| `metadata.openapi.parameters` | path/query/header/cookie parameter |
| `metadata.openapi.security` | OpenAPI security requirement |
| `metadata.openapi.path_module` | deterministic path/module cluster |
| `metadata.request_body_schema` | request body schema summary |
| `metadata.response_schema` | response schema summary |
| `metadata.content_types` | request/response content type |
| `metadata.api_contract` | consumes, produces, links, contract evidence |
| `metadata.ai_metadata` | search에 쓰이는 semantic metadata |

`ai_metadata`에는 `canonical_action`, `primary_resource`, `one_line_summary`,
`when_to_use`, `result_shape`, `semantic_confidence`, `semantic_evidence`가
들어갈 수 있습니다.

## Edge evidence

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

manual, LLM-curated, OpenAPI link, run-observed edge는
`normalize_graph_edge()`와 `merge_graph_edges()`로 같은 정책으로 합칠 수
있습니다.

## 호환성 규칙

- field 이름을 바꾸기보다 additive field를 추가합니다.
- rebuild 때 알 수 없는 field를 보존합니다.
- raw token, cookie, API key, 사용자 식별값은 artifact에 저장하지 않습니다.
- learning/trace evidence 저장 전에는 민감값을 scrub합니다.

## 관련 문서

- [Collection Artifacts](../build/collection-artifacts.md)
- [Report Schema](./report-schemas.md)
- [Event Schema](./event-schemas.md)
- [Compatibility](./compatibility.md)
