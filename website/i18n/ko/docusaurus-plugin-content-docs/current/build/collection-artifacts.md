---
title: Collection Artifacts
description: graph metadata, readiness report, quality summary를 가진 portable OpenAPI collection artifact를 만듭니다.
---

# Collection Artifacts

Collection artifact는 API collection의 portable JSON 표현입니다. product adapter는
graph를 한 번 저장한 뒤 retrieval, target selection, planning, validation, UI
inspection에 재사용할 수 있습니다.

artifact는 product와 engine 사이의 boundary입니다. engine은 product-neutral evidence를
만들고, adapter는 저장 위치, 실행 인증, 진단 UI를 책임집니다.

## 최소 예제

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact("openapi.json")
print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

## Adapter Option과 함께 Build

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

alias는 adapter가 generic option으로 넘깁니다. library에는 특정 고객사의 private field
dictionary를 넣지 않습니다.

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

## Version과 Provenance

artifact를 재현할 수 있도록 build metadata를 저장합니다.

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

운영자가 직접 수정한 field는 명시적으로 overwrite를 요청하지 않는 한 rebuild에서
덮어쓰지 않습니다. metadata preservation이 product 사용 안정성의 핵심입니다.

## Adapter Notes

Adapter는 rebuild 중에도 `ai_metadata`, `context_defaults`, `enum_mappings`,
manual edge, quality case, promoted learning suggestion 같은 운영자 수정을
보존해야 합니다.

## Rebuild Policy

source가 바뀌면 다음 순서로 처리합니다.

1. 새 source를 fetch 또는 load합니다.
2. 새 engine artifact를 build합니다.
3. product-owned field를 merge 보존합니다.
4. readiness와 quality gate를 다시 실행합니다.
5. blocker가 해소된 경우에만 artifact를 승격합니다.

merge step에서 보존해야 하는 항목은 다음과 같습니다.

- manually curated `ai_metadata`
- `context_defaults`
- `enum_mappings`
- manual/promoted trace edge
- `quality_lab.cases`와 마지막 결과 요약
- status가 있는 `learning.suggestions`

## UI Checklist

collection 상세 화면에는 다음이 보여야 합니다.

- tool/edge count
- semantic coverage
- edge quality summary
- readiness status와 top issue
- source version/provenance
- 마지막 Quality Lab result
- auth 또는 readiness 때문에 execution이 막혔는지

대형 collection graph는 먼저 요약 cluster로 보여주고, 사용자가 module/resource/target
workflow로 범위를 좁힌 뒤 dense edge를 렌더링해야 합니다.

## 검증

build option이나 stored schema를 바꾸면 collection artifact test를 실행합니다.

```bash
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## 관련 문서

- [Readiness Diagnostics](./readiness-diagnostics.md)
- [OpenAPI Collections](../guides/openapi-collections.md)
- [XGEN API Collection](../guides/xgen-integration.md)
