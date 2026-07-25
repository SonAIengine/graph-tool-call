---
title: Semantic Build
description: raw tool definition에서 action, resource, module, result-shape metadata를 deterministic하게 추론합니다.
---

# Semantic Build

Semantic build는 search와 target selection이 사용할 deterministic metadata로 raw
tool schema를 보강합니다.

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

## Quality Checks

빌드 후 아래 rate를 추적합니다.

- action known rate
- resource assigned rate
- module assigned rate
- result shape known rate
- unknown samples

## 관련 문서

- [Target Selection](../search/target-selection.md)
- [XGEN Scale Gates](../validation/xgen-scale-gates.md)
