# OpenAPI 의미 빌드

OpenAPI spec에는 수백, 수천 개 operation이 있고 operationId, tag, summary,
schema, response envelope이 일관되지 않은 경우가 많습니다. semantic build pass는
이 raw catalog를 agent가 사용할 수 있는 metadata로 바꿉니다.

## 파생 Metadata

각 operation에 대해 엔진은 다음을 파생할 수 있습니다.

- `canonical_action`: `search`, `read`, `create`, `update`, `delete`, `action`, `unknown`
- `primary_resource`: 주요 business/resource 개념
- `path_module`: 안정적인 path/module cluster
- `result_shape`: `single`, `list`, `count`, `mutation`, `unknown`
- `semantic_confidence`, `semantic_evidence`

## Contract Metadata

OpenAPI contract extraction은 다음을 보존합니다.

- path/query/header/cookie parameter
- request body field
- response field
- content type
- security requirement
- response envelope candidate

LLM reasoning 전에 search와 planning이 쓸 deterministic 기반을 제공합니다.

