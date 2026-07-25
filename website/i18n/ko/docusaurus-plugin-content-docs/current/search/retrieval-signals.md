---
title: Retrieval Signals
description: graph-tool-call 검색 결과에 영향을 주는 ranking evidence를 설명합니다.
---

# Retrieval Signals

Retrieval은 설명 가능해야 합니다. candidate는 prompt가 우연히 선호해서가 아니라,
이름 붙은 signal 때문에 이겨야 합니다.

## Core Signals

| Signal | Source |
| --- | --- |
| `keyword_match` | tool name, operation id, summary, description |
| `action_match` | `metadata.ai_metadata.canonical_action` |
| `resource_match` | `metadata.ai_metadata.primary_resource` |
| `module_match` | `metadata.openapi.path_module` 또는 operation group |
| `shape_match` | `metadata.ai_metadata.result_shape` |
| `contract_match` | request/response contract field |
| `graph_expansion` | related producer 또는 curated link edge |
| `learning` | promoted trace-learning suggestion |

## Best Practice

product debug screen과 regression fixture에는 `include_evidence=True`를
사용합니다. ranking을 설명하는 compact evidence만 저장하고 raw secret이나 full API
payload는 저장하지 않습니다.

## 관련 문서

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
