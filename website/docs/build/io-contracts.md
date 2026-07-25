---
title: IO Contracts
description: Extract request and response field contracts that explain tool compatibility.
---

# IO Contracts

IO contracts describe what each tool consumes and produces. They make graph
edges, candidate expansion, plan synthesis, and execution diagnostics
explainable.

Without contracts, a tool graph can still search by text. With contracts, it can
also answer operational questions: "Which tool can produce `orderNo`?", "Which
target requires `memberNo`?", "Is this missing field user input, context, or
auth?"

## Contract Model

Each operation can have three contract surfaces:

| Surface | Meaning |
| --- | --- |
| `consumes` | Fields the operation needs in request path, query, header, cookie, or body |
| `produces` | Fields the operation returns in response body or envelope |
| `links` | Explicit or inferred relationships between operations |

Contract entries are stored under `metadata.api_contract` on each `ToolSchema`.

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
| `semantic_tag` | Generic role such as paging, search, identifier, or producer |

## Public Contract Index

Use `extract_openapi_contract_index()` when an adapter needs operation-level
facts without depending on private parser helpers.

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
| `version` | Contract index schema version |
| `operation_count` | Number of operations included |
| `operations` | Operation-level contract rows |
| `by_operation_id` | Lookup map from operation id to operation key |
| `by_tool_name` | Lookup map from tool name to operation key |
| `by_method_path` | Lookup map from `METHOD /path` to operation key |
| `summary` | Coverage and field-count summary |

Each operation row includes method, path, operation id, parameters, request body
schema, response schema, content types, security hints, `api_contract`,
`openapi`, and full normalized metadata.

## Field Kind Classification

The engine keeps classification generic:

| Kind | Use |
| --- | --- |
| `data` | Business data supplied by the user, a producer tool, or static defaults |
| `context` | Runtime context supplied by the adapter, such as tenant or site |
| `auth` | Authentication or authorization material |

Pass adapter-specific field names as options:

```python
artifact = build_openapi_collection_artifact(
    "openapi.json",
    context_field_names={"mallNo", "siteNo"},
    auth_field_names={"Authorization", "accessToken"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchType"},
)
```

The engine should classify the fields. The adapter should provide runtime
values.

## How Contracts Affect Search

Contracts improve search and selection through:

- `contract_match` score signals
- producer expansion for required target fields
- `result_shape` hints from response structure
- user input slot detection
- auth readiness diagnostics
- failure reason classification

## Readiness Checks

Useful thresholds vary by domain, but these are strong warning signs:

- `response_schema_coverage` is low for read/search APIs
- `produces_field_count` is near zero
- many required consumes fields have no default, producer, or user slot
- auth fields are classified as `data`
- envelope responses hide the actual business result body

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| Missing producer tools | Response schema leaves were not extracted | `api_contract.produces` |
| Too many producer tools | Common field names are too broad | producer cap and semantic tags |
| Required fields become user prompts | Context defaults or producer edges are missing | `context_field_names`, graph edges |
| Auth fields appear in UI forms | Auth names were not classified | `auth_field_names`, OpenAPI security |
| List/detail confusion | Response shape is missing or ambiguous | `response_schema`, `result_shape` |

## Related Pages

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Candidate Expansion](../search/candidate-expansion.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Auth Readiness](./auth-readiness.md)
