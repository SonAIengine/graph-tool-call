---
title: IO Contracts
description: tool compatibility를 설명하는 request/response field contract를 추출합니다.
---

# IO Contracts

IO contract는 각 tool이 무엇을 소비하고 생산하는지 설명합니다. graph edge와 plan
synthesis를 설명 가능하게 만드는 핵심 근거입니다.

## Contract Fields

| Field | Purpose |
| --- | --- |
| `name` | leaf field 또는 parameter name |
| `path` | request/response schema 안의 위치 |
| `location` | `query`, `path`, `header`, `cookie`, `body`, `response` |
| `required` | operation이 요구하는 필드인지 |
| `kind` | `data`, `context`, `auth` |
| `field_type` | JSON schema type |
| `enum` | allowed values |
| `semantic_tag` | paging, search, identifier 같은 generic role |

## Public Helper

```python
from graph_tool_call.graphify import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")
for operation in index["operations"]:
    print(operation["operationId"], operation["api_contract"])
```

## 왜 중요한가

Search는 contract field를 사용해 사용자가 요청한 resource나 result shape와 맞는
tool을 찾을 수 있습니다. Plan synthesis는 같은 field로 missing input, producer
tool, user input slot, auth requirement를 판단합니다.

## 관련 문서

- [Candidate Expansion](../search/candidate-expansion.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
