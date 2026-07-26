# GraphQL Introspection Ingest

## Goal

Convert a standard GraphQL introspection response into the same contract-rich
`ToolSchema` catalog used by OpenAPI, MCP, and Python tools. The adapter is
product-neutral and does not contain XGEN, customer, domain, field, or endpoint
rules.

The implementation follows the GraphQL introspection model defined by the
[GraphQL specification](https://spec.graphql.org/September2025/#sec-Introspection).

## Public API

```python
from graph_tool_call import ingest_graphql_introspection, ingest_source

result = ingest_graphql_introspection(
    introspection_response,
    endpoint_url="https://api.example.com/graphql",
)

# Equivalent auto-detected path.
result = ingest_source(
    introspection_response,
    endpoint_url="https://api.example.com/graphql",
)
```

Accepted source shapes:

- `{"data": {"__schema": ...}}`
- `{"__schema": ...}`
- a UTF-8 JSON string or bytes value
- a local UTF-8 JSON file up to 20 MB

The adapter does not fetch a GraphQL endpoint. A caller such as XGEN or
Pathfinder owns URL access policy, authentication, introspection execution, and
credential storage.

## Tool identity

Every root field becomes one tool:

| GraphQL field | Tool name |
|---|---|
| `Query.customer` | `query_customer` |
| `Mutation.updateCustomer` | `mutation_updateCustomer` |
| `Subscription.customerChanged` | `subscription_customerChanged` |

The operation type prefix prevents query/mutation collisions and remains stable
when another root field is added later.

## Schema conversion

- `NON_NULL` controls JSON Schema `required`.
- `LIST` becomes `type: array`.
- built-in scalars map to their JSON equivalents.
- custom scalars remain strings with `x-graphql-scalar`.
- enum values remain JSON Schema `enum`.
- input objects retain nested properties and required fields.
- recursive input objects stop expansion and record `x-graphql-recursive`.
- response schemas retain the `data.<root field>` envelope.

Generated operation documents use variables rather than inline argument values.
Object selections include `__typename` and bounded scalar/enum fields.
Fields requiring additional arguments are not selected automatically.

## Execution descriptor

Each tool records:

```json
{
  "execution": {
    "transport": "graphql-http",
    "method": "POST",
    "endpoint": "https://api.example.com/graphql",
    "content_type": "application/json",
    "body_template": {
      "query": "query GtcQueryCustomer($id: ID!) { ... }",
      "operationName": "GtcQueryCustomer"
    },
    "variable_binding": "arguments_to_variables",
    "result_path": ["data", "customer"],
    "read_only": true
  }
}
```

Runtime arguments are placed under the GraphQL request body's `variables`
member. Credential headers are never part of the descriptor.

## Diagnostics

| Code | Severity | Meaning |
|---|---|---|
| `invalid_graphql_introspection` | blocker | No standard `__schema` payload |
| `graphql_endpoint_required` | blocker | Schema is inspectable but not executable |
| `graphql_endpoint_invalid` | blocker | Endpoint contains unsafe or invalid URL facts |
| `graphql_introspection_partial_errors` | warning | Response contained errors; only the count is retained |
| `graphql_deprecated_fields_skipped` | warning | Deprecated root fields were excluded |
| `graphql_subscription_transport_required` | warning | A streaming execution adapter is required |

The result stores a deterministic SHA-256 schema fingerprint, operation counts,
and type count. Raw introspection errors and credential values are not
persisted.

## XGEN boundary

`graph-tool-call` parses the protocol and creates the canonical descriptor.
XGEN is responsible for:

- resolving and enforcing URL safety for private/internal endpoints
- obtaining introspection with the active auth profile
- persisting the source and adapter diagnostics
- translating runtime arguments to `variables`
- forwarding session/auth headers without logging values
- supplying a subscription transport when enabled

This keeps protocol parsing reusable while authentication, DB, UI, and network
policy remain in the product adapter.
