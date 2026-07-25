---
title: OpenAPI Ingestion
description: Swagger 또는 OpenAPI source를 graph-tool-call tool schema로 정규화합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# OpenAPI Ingestion

OpenAPI ingestion은 Swagger 2.0과 OpenAPI 3.x source를 정규화된 `ToolSchema`로
변환합니다. 각 HTTP operation은 method, path, operation id, summary, parameter,
schema, security hint, semantic metadata, IO contract를 가진 searchable tool이
됩니다.

이 페이지는 engine-level ingestion 경로를 설명합니다. DB row, user session, auth
profile, cookie, HTTP execution 같은 product concern은 adapter 책임입니다.

## 언제 사용하나

다음 상황에서 사용합니다.

- tool catalog가 Swagger UI URL 또는 직접 JSON/YAML spec에서 시작함
- 하나의 API collection에 수백, 수천 개 operation이 있음
- operation description에 noise가 많아 deterministic metadata가 필요함
- planning과 execution을 위해 request/response contract가 필요함
- 나중에 UI에서 점검하고 검증할 stored artifact가 필요함

live credential을 붙이는 용도로 ingestion을 사용하지 않습니다. Runtime auth는
adapter가 plan을 실행하는 시점에만 해석해야 합니다.

## Source Types

| Source | Supported Shape | Notes |
| --- | --- | --- |
| Direct file | `openapi.json`, `swagger.yaml` | 재현 가능한 local test에 적합 |
| Direct URL | `https://.../openapi.json` | remote fetch는 URL safety option을 따름 |
| Swagger UI URL | `https://.../swagger-ui/index.html` | engine이 backing spec URL을 발견 |
| Python dict | already-loaded spec | test와 product adapter에 유용 |
| Sequence | multiple specs | collection artifact builder에서 사용 |

private/internal URL은 기본적으로 차단됩니다. 신뢰된 infrastructure에서만
`allow_private_hosts=True`를 전달합니다.

## Minimal Flow

artifact를 어떻게 사용할지에 따라 entry point를 고릅니다.

<Tabs>
  <TabItem value="python" label="Python graph" default>

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")

for tool in graph.retrieve("find pets by status", top_k=5):
    print(tool.name, tool.description)
```

  </TabItem>
  <TabItem value="cli" label="CLI search">

```bash
graph-tool-call search "find pets by status" \
  --source https://petstore3.swagger.io/api/v3/openapi.json \
  --top-k 5 \
  --scores
```

  </TabItem>
  <TabItem value="artifact" label="Collection artifact">

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  -o collection.json \
  --context-field siteNo \
  --paging-field page,size \
  --search-filter-field keyword,searchType
```

  </TabItem>
  <TabItem value="readiness" label="Readiness">

```bash
graph-tool-call inspect-openapi ./openapi.json --json
```

  </TabItem>
</Tabs>

빠른 source smoke test에는 `search`, 코드 연결에는 `ToolGraph.from_url()`,
product가 graph와 readiness/semantic/edge-quality metadata를 저장해야 할 때는
`build-openapi-collection`을 사용합니다.

## Collection Artifact 만들기

product adapter가 결과를 저장하거나 UI에서 inspect해야 한다면
`build_openapi_collection_artifact()`를 사용합니다.

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
| `required_only` | `False` | ingest 중 required schema field만 유지 |
| `skip_deprecated` | `True` | deprecated OpenAPI operation 제외 |
| `allow_private_hosts` | `False` | private/internal URL fetch 허용 |
| `max_response_bytes` | `5_000_000` | remote spec size 제한 |
| `promote_contract_signals` | `True` | request/response field를 graph evidence로 승격 |
| `max_contract_producers_per_field` | `3` | field별 producer expansion 상한 |
| `derive_semantic_metadata` | `True` | action/resource/module/result-shape metadata 추론 |
| `overwrite_ai_metadata` | `False` | 기본적으로 manual metadata 보존 |
| `context_field_names` | `None` | adapter가 전달하는 generic context field name |
| `auth_field_names` | `None` | adapter가 전달하는 auth field name |
| `paging_field_names` | `None` | adapter가 전달하는 paging field name |
| `search_filter_field_names` | `None` | adapter가 전달하는 search/filter field name |
| `metadata` | `None` | artifact에 붙일 product-neutral metadata |

product-specific alias는 option으로 전달합니다. engine에 product term을
하드코딩하지 않습니다.

## Output Shape

Collection artifact는 일반 graph save shape를 유지하면서 product-facing build
fact를 추가합니다.

| Section | Purpose |
| --- | --- |
| `graph` | serialized graph |
| `tools` | normalized tool schema |
| `metadata` | build version, source, options, collection graph version |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | data-flow, structural, manual, trace, evidence count |
| `readiness_report` | deterministic readiness diagnostics |
| `source_snapshot_manifest` | source identity and hash information |
| `ingest_summary` | operation and duplicate handling summary |

## Stable OpenAPI Metadata

OpenAPI-derived tool에는 아래 metadata가 포함될 수 있습니다.

| Field | Purpose |
| --- | --- |
| `metadata.openapi.method` | HTTP method |
| `metadata.openapi.path` | operation path |
| `metadata.openapi.operation_id` | stable operation identifier |
| `metadata.openapi.parameters` | query, path, header, cookie parameter |
| `metadata.openapi.security` | OpenAPI security hint |
| `metadata.request_body_schema` | request body schema summary |
| `metadata.response_schema` | response schema summary |
| `metadata.api_contract` | engine-level consumes, produces, links |
| `metadata.ai_metadata` | deterministic semantic action/resource/module field |

## Diagnostics

execution을 허용하기 전에 아래 section을 확인합니다.

```python
summary = artifact["readiness_report"]["summary"]
semantic = artifact["semantic_summary"]
edges = artifact["edge_quality_summary"]

print(summary["status"], summary["readiness_score"])
print(semantic["canonical_action_known_rate"])
print(edges["strong_deterministic_evidence_count"])
```

중요 signal:

- missing request/response schema
- 낮은 semantic action/resource coverage
- weak edge evidence
- auth required지만 adapter readiness에 표현되지 않음
- 하나의 module에 너무 많은 unrelated tool이 몰림

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| tool이 생성되지 않음 | spec URL이 틀렸거나 Swagger UI discovery 실패 | direct spec URL 사용 또는 trusted private host 허용 |
| response contract 누락 | OpenAPI response schema가 없거나 unsupported content | spec repair 또는 adapter-side contract repair |
| `unknown` action이 많음 | operation id와 summary가 약함 | generic alias 또는 curated semantic metadata 추가 |
| producer expansion이 없음 | response field가 추출되지 않음 | `metadata.api_contract.produces` 확인 |
| auth가 일반 data로 보임 | auth field name이 product-specific | adapter에서 `auth_field_names` 전달 |

## 관련 문서

- [IO Contracts](./io-contracts.md)
- [Semantic Build](./semantic-build.md)
- [Readiness Diagnostics](./readiness-diagnostics.md)
- [Collection Artifacts](./collection-artifacts.md)
