---
title: IO Contracts
description: Extract request and response field contracts that explain tool compatibility.
---

# IO Contracts

IO contracts describe what each tool consumes and produces. They make graph
edges and plan synthesis explainable.

## Contract Fields

Consumes and produces entries may include:

| Field | Purpose |
| --- | --- |
| `name` | Leaf field or parameter name |
| `path` | Location inside the request or response schema |
| `location` | `query`, `path`, `header`, `cookie`, `body`, or `response` |
| `required` | Whether the field is required by the operation |
| `kind` | `data`, `context`, or `auth` |
| `field_type` | JSON schema type when available |
| `enum` | Allowed values when available |
| `semantic_tag` | Generic role such as paging, search, or identifier |

## Public Helper

```python
from graph_tool_call.graphify import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")
for operation in index["operations"]:
    print(operation["operationId"], operation["api_contract"])
```

## Why It Matters

Search can use contract fields to find tools that match the user's requested
resource or result shape. Plan synthesis can use the same fields to detect
missing inputs, producer tools, user input slots, and auth requirements.

## Related Pages

- [Candidate Expansion](../search/candidate-expansion.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
