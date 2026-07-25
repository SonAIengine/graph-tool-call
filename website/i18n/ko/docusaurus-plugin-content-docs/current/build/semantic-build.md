---
title: Semantic Build
description: raw tool definition에서 action, resource, module, result-shape metadata를 deterministic하게 추론합니다.
---

# Semantic Build

Semantic build는 search와 target selection이 사용할 deterministic metadata로 raw
tool schema를 보강합니다.

대형 spec이 익명 `unknown` action이나 `unassigned` resource 상태로 남지 않도록 OpenAPI
collection build 중에 semantic build를 실행합니다.

## 생성 Metadata

| Field | Meaning |
| --- | --- |
| `canonical_action` | `search`, `read`, `create`, `update`, `delete`, `action`, `unknown` |
| `primary_resource` | operation이 다루는 주 resource |
| `path_module` | path에서 나온 안정 module/group |
| `operation_group` | higher-level operation grouping |
| `result_shape` | `single`, `list`, `count`, `mutation`, `unknown` |
| `semantic_confidence` | deterministic confidence signal |
| `semantic_evidence` | metadata를 설명하는 evidence source |

## Priority Rules

엔진은 기존 curated metadata를 먼저 존중합니다. 없으면 operation id, summary,
description, HTTP method, path segment, tag, schema reference, identifier field를
사용합니다.

product-specific dictionary는 option으로 전달해야 하며 라이브러리에 하드코딩하지
않습니다.

## 최소 예제

```python
from graph_tool_call.graphify.semantics import annotate_openapi_tool_semantics

tools = annotate_openapi_tool_semantics(
    tools,
    options={
        "resource_aliases": {"member": ["customer", "user"]},
        "action_aliases": {"search": ["find", "lookup"]},
        "module_aliases": {"orders": ["claim", "refund"]},
    },
    overwrite=False,
)
```

`overwrite=False`는 운영자가 curate한 metadata를 보존합니다. source 기준으로 semantic
field를 의도적으로 다시 만들 때만 overwrite를 사용합니다.

## Artifact Summary

collection artifact는 semantic coverage를 노출해야 합니다.

```json
{
  "semantic_summary": {
    "canonical_action_known_rate": 0.96,
    "primary_resource_assigned_rate": 0.82,
    "path_module_assigned_rate": 0.99,
    "result_shape_known_rate": 0.74,
    "unknown_samples": ["legacyAction", "executeProc"]
  }
}
```

낮은 rate는 단순 표시 문제가 아닙니다. search ranking, target selection, graph
visualization에 직접 영향을 줍니다.

## Quality Checks

빌드 후 아래 rate를 추적합니다.

- action known rate
- resource assigned rate
- module assigned rate
- result shape known rate
- unknown samples

## Failure Mode

| 증상 | 가능 원인 | 보완 |
| --- | --- | --- |
| `unknown` action이 많음 | operation id와 summary가 약함 | action alias 전달 또는 metadata curate |
| unassigned resource가 많음 | broad tag 또는 generic path name | resource alias 전달 또는 path module 점검 |
| 하나의 module에 tool이 몰림 | module derivation이 너무 coarse함 | module alias 또는 source grouping 조정 |
| detail query가 list tool 선택 | `result_shape` 누락/오류 | schema와 summary hint 개선 |

## 관련 문서

- [Target Selection](../search/target-selection.md)
- [OpenAPI Semantic Build](../concepts/openapi-semantic-build.md)
- [XGEN Scale Gates](../validation/xgen-scale-gates.md)
