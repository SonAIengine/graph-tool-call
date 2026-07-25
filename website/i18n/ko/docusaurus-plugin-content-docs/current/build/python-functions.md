---
title: Python Functions
description: 로컬 Python function을 retrieval과 planning에 사용할 ToolSchema로 변환합니다.
---

# Python Functions

Python function ingestion은 API spec이 아니라 application code에서 tool catalog를
만들 때 유용합니다.

function name, type hint, signature, 첫 docstring line을 사용해 callable을
`ToolSchema`로 변환합니다. 이 경로는 의도적으로 가볍습니다. local tool과 test에는
좋지만 OpenAPI 수준의 풍부한 contract discovery를 대체하지는 않습니다.

## Minimal Example

```python
from graph_tool_call import ToolGraph

def lookup_customer(customer_id: str, include_orders: bool = False) -> dict:
    """Look up a customer profile."""
    return {}

def search_orders(customer_id: str, status: str | None = None) -> list[dict]:
    """Search orders for a customer."""
    return []

graph = ToolGraph()
tools = graph.ingest_functions([lookup_customer, search_orders])

for tool in tools:
    print(tool.name, tool.description)
```

function name은 tool name이 되고, 첫 docstring line은 description이 됩니다. default가
없는 parameter는 required입니다.

## 언제 쓰나

- 내부 automation function
- test fixture
- 빠른 실험
- non-HTTP system을 감싼 custom adapter
- local evaluation dataset

대형 HTTP API collection은 [OpenAPI Ingestion](./openapi-ingestion.md)을 우선합니다.
request/response contract, auth, content type, schema evidence를 보존할 수 있기
때문입니다.

## Extraction Rules

| Source | Extracted As |
| --- | --- |
| `fn.__name__` | `ToolSchema.name` |
| 첫 non-empty docstring line | `ToolSchema.description` |
| Python signature | tool parameters |
| type hints | JSON-schema-like primitive parameter type |
| default value 없음 | `required=True` |

`*args`, `**kwargs`, `self`, `cls`는 무시합니다.

## Contract Guidance

Function tool은 signature와 docstring이 아래 내용을 설명할수록 잘 동작합니다.

- required argument
- optional argument
- return shape
- failure behavior
- side effect

이 정보가 retrieval과 planning evidence가 됩니다.

예시 docstring:

```python
def cancel_order(order_id: str, reason: str) -> dict:
    """Cancel an order and return cancellation status."""
```

## Limits

Python function ingestion은 아래 정보를 자동으로 알 수 없습니다.

- response schema leaf
- HTTP method 또는 path
- auth requirement
- paging semantic
- enum label mapping
- external side-effect safety

이 정보가 중요하다면 ingestion 이후 metadata를 추가하거나 더 풍부한 source에서 catalog를
build합니다.

## Validation

function name과 docstring만으로 expected query가 검색되는지 `retrieve_with_scores()`로
확인합니다.

```python
results = graph.retrieve_with_scores("cancel an order", top_k=3)
print([(row.tool.name, row.score) for row in results])
```

planning workflow에서는 producer/consumer 관계가 `PathSynthesizer`에 보이도록 IO
contract metadata를 adapter나 수동 metadata로 추가합니다.

## 관련 문서

- [Mental Model](../getting-started/mental-model.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [IO Contracts](./io-contracts.md)
- [Direct API](../integrations/direct-api.md)
