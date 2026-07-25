---
sidebar_position: 2
title: GraphQL introspection
description: Turn a GraphQL schema introspection response into searchable, executable tools.
---

# GraphQL introspection

GraphQL introspection describes the query, mutation, and subscription fields
available on a schema. `graph-tool-call` converts each root field into a
contract-rich tool with argument schemas, result schemas, graph evidence, and a
variable-based operation document.

## Ingest a schema

```python
from graph_tool_call import ingest_graphql_introspection

result = ingest_graphql_introspection(
    introspection_response,
    endpoint_url="https://api.example.com/graphql",
)

print(result.ready)
print([tool.name for tool in result.tools])
```

`ingest_source()` auto-detects the standard `data.__schema` and `__schema`
envelopes as `graphql-introspection`.

## Why the endpoint is separate

The GraphQL introspection schema does not contain the service endpoint. Pass it
explicitly when the catalog must be executable. Without it, tools remain
inspectable but the result contains the `graphql_endpoint_required` blocker.

The endpoint must be an absolute HTTP(S) URL without userinfo credentials,
sensitive query parameters, or fragments. Runtime authorization remains in
your application auth adapter.

## Generated contract

For a field such as `Query.customer(id: ID!): Customer`, the adapter creates:

- tool name `query_customer`
- required `id` input
- a stable variable-based operation document
- JSON Schemas for variables and the `data.customer` response
- `api_contract.produces/consumes` evidence
- `metadata.execution` with endpoint, body template, and result path
- read-only MCP annotations

Mutation fields are conservatively marked destructive. Subscription fields are
searchable, but report `graphql_subscription_transport_required` until the
application supplies its own WebSocket or SSE transport.

## Boundaries

The library does not fetch introspection, store credentials, or choose a
customer-specific endpoint. XGEN, a browser extension, or another application
owns network access, authentication, persistence, and runtime header
forwarding.
