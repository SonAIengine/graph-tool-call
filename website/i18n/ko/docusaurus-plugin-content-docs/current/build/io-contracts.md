---
title: IO Contracts
description: tool compatibility를 설명하는 request/response field contract를 추출합니다.
---

# IO Contracts

IO contract는 각 tool이 무엇을 소비하고 생산하는지 설명합니다. graph edge,
candidate expansion, plan synthesis, execution diagnostics를 설명 가능하게 만드는
핵심 근거입니다.

contract가 없으면 text 기반 검색은 가능합니다. contract가 있으면 "어떤 tool이
`orderNo`를 생산하는가?", "target이 `memberNo`를 요구하는가?", "이 missing field는
user input인가 context인가 auth인가?" 같은 운영 질문에 답할 수 있습니다.

## Contract Model

각 operation은 세 가지 contract surface를 가질 수 있습니다.

| Surface | Meaning |
| --- | --- |
| `consumes` | request path, query, header, cookie, body에서 필요한 field |
| `produces` | response body 또는 envelope에서 반환하는 field |
| `links` | explicit 또는 inferred operation relationship |

Contract entry는 각 `ToolSchema`의 `metadata.api_contract`에 저장됩니다.

## Contract Fields

| Field | Purpose |
| --- | --- |
| `name` | leaf field 또는 parameter name |
| `path` | request/response schema 안의 위치 |
| `location` | `query`, `path`, `header`, `cookie`, `body`, `response` |
| `required` | operation이 요구하는 field인지 |
| `kind` | `data`, `context`, `auth` |
| `field_type` | JSON schema type |
| `enum` | allowed values |
| `semantic_tag` | paging, search, identifier, producer 같은 generic role |

## Public Contract Index

adapter가 private parser helper에 의존하지 않고 operation-level fact를 얻고 싶다면
`extract_openapi_contract_index()`를 사용합니다.

```python
from graph_tool_call.graphify import extract_openapi_contract_index

index = extract_openapi_contract_index(
    "openapi.json",
    required_only=False,
    skip_deprecated=True,
)

print(index["summary"]["response_schema_coverage"])

for operation in index["operations"]:
    print(operation["method"], operation["path"])
    print(operation["api_contract"]["consumes"])
    print(operation["api_contract"]["produces"])
```

## Index Shape

| Field | Meaning |
| --- | --- |
| `version` | contract index schema version |
| `operation_count` | included operation count |
| `operations` | operation-level contract rows |
| `by_operation_id` | operation id에서 operation key로 가는 lookup |
| `by_tool_name` | tool name에서 operation key로 가는 lookup |
| `by_method_path` | `METHOD /path`에서 operation key로 가는 lookup |
| `summary` | coverage와 field count summary |

각 operation row는 method, path, operation id, parameter, request body schema,
response schema, content type, security hint, `api_contract`, `openapi`, normalized
metadata를 포함합니다.

## Field Kind Classification

엔진은 분류를 generic하게 유지합니다.

| Kind | Use |
| --- | --- |
| `data` | user, producer tool, static default에서 공급되는 business data |
| `context` | adapter가 공급하는 tenant, site 같은 runtime context |
| `auth` | authentication 또는 authorization material |

adapter-specific field name은 option으로 전달합니다.

```python
artifact = build_openapi_collection_artifact(
    "openapi.json",
    context_field_names={"mallNo", "siteNo"},
    auth_field_names={"Authorization", "accessToken"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchType"},
)
```

엔진은 field를 classify하고, adapter는 runtime value를 제공합니다.

## Search에 미치는 영향

Contract는 아래 방식으로 search와 selection을 개선합니다.

- `contract_match` score signal
- required target field에 대한 producer expansion
- response structure 기반 `result_shape` hint
- user input slot detection
- auth readiness diagnostics
- failure reason classification

## Readiness Checks

domain마다 threshold는 다르지만 아래는 강한 warning sign입니다.

- read/search API의 `response_schema_coverage`가 낮음
- `produces_field_count`가 거의 0임
- required consumes field 중 default, producer, user slot이 없는 field가 많음
- auth field가 `data`로 분류됨
- envelope response 때문에 실제 business result body가 숨겨짐

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| producer tool 누락 | response schema leaf가 추출되지 않음 | `api_contract.produces` |
| producer tool이 너무 많음 | common field name이 너무 넓음 | producer cap, semantic tag |
| required field가 모두 user prompt가 됨 | context default 또는 producer edge 누락 | `context_field_names`, graph edge |
| auth field가 UI form에 표시됨 | auth name이 분류되지 않음 | `auth_field_names`, OpenAPI security |
| list/detail target 혼동 | response shape가 없거나 모호함 | `response_schema`, `result_shape` |

## 관련 문서

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Candidate Expansion](../search/candidate-expansion.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](./auth-readiness.md)
