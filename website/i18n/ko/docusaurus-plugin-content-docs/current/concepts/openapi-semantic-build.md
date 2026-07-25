---
title: OpenAPI 의미 빌드
description: raw OpenAPI operation을 검색과 target selection이 사용할 수 있는 semantic metadata로 바꾸는 deterministic pass입니다.
---

# OpenAPI 의미 빌드

OpenAPI spec에는 수백, 수천 개 operation이 있고 operationId, tag, summary,
schema, response envelope이 일관되지 않은 경우가 많습니다. semantic build pass는
이 raw catalog를 agent가 사용할 수 있는 metadata로 바꿉니다.

이 pass는 기본적으로 deterministic입니다. LLM enrichment를 하기 전에 graph가 검색과
검토에 더 적합한 형태가 되도록 만드는 것이 목적입니다.

## 왜 필요한가

대형 enterprise spec은 raw tool catalog 품질이 낮은 경우가 많습니다.

- operation 이름이 generic하거나 중복됨
- summary에 업무 설명, release note, HTML fragment가 섞임
- tag가 없거나 너무 넓음
- list/detail/count operation이 서로 비슷하게 보임
- response envelope이 실제 body field를 숨김

semantic build는 retrieval과 target selection이 직접 사용할 수 있는 안정 필드를 만듭니다.

## 파생 Metadata

각 operation에 대해 엔진은 다음을 파생할 수 있습니다.

- `canonical_action`: `search`, `read`, `create`, `update`, `delete`, `action`, `unknown`
- `primary_resource`: 주요 business/resource 개념
- `path_module`: 안정적인 path/module cluster
- `result_shape`: `single`, `list`, `count`, `mutation`, `unknown`
- `semantic_confidence`, `semantic_evidence`

## 파생 우선순위

| Field | 우선순위 |
| --- | --- |
| action | 기존 metadata, operationId verb, summary/description verb, HTTP method |
| resource | 기존 metadata, tag, stable path segment, operationId noun, schema/ref field |
| module | stable path/module segment, operation group, source label |
| shape | operationId/summary hint, response schema shape, mutation method |

사람이 수정한 기존 metadata는 caller가 overwrite를 명시하지 않는 한 덮어쓰지 않습니다.

## Contract Metadata

OpenAPI contract extraction은 다음을 보존합니다.

- path/query/header/cookie parameter
- request body field
- response field
- content type
- security requirement
- response envelope candidate

LLM reasoning 전에 search와 planning이 쓸 deterministic 기반을 제공합니다.

## 생성되는 JSON

```json
{
  "metadata": {
    "ai_metadata": {
      "canonical_action": "search",
      "primary_resource": "order",
      "result_shape": "list",
      "semantic_confidence": 0.88
    },
    "openapi": {
      "path_module": "/api/orders",
      "operation_group": "Order"
    }
  }
}
```

## 품질 Signal

artifact summary에서 다음 coverage를 추적합니다.

- canonical action known rate
- primary resource assigned rate
- path/module assigned rate
- result shape known rate
- unknown samples
- weak edge evidence count

## Failure Mode

| 증상 | 가능 원인 | 보완 |
| --- | --- | --- |
| `unknown` action이 많음 | operation id와 summary가 약함 | generic action alias 추가 |
| `unassigned` resource가 많음 | tag/path segment가 너무 넓음 | resource alias 또는 source grouping 추가 |
| 하나의 거대한 module cluster | path module derivation이 너무 coarse함 | `path_module` rule 점검 |
| list/detail tool이 동률 | `result_shape`가 부족함 | schema/summary hint 개선 |
| graph에 약한 edge가 너무 많음 | structural edge가 과사용됨 | visual/execution edge를 evidence 기준으로 필터 |

## 관련 문서

- [Semantic Build](../build/semantic-build.md)
- [OpenAPI Collections](../guides/openapi-collections.md)
- [Search Tuning](../search/search-tuning.md)
