# OpenAPI Semantic Build

OpenAPI specs often contain hundreds or thousands of operations with inconsistent
operation IDs, tags, summaries, schemas, and response envelopes. The semantic
build pass turns that raw catalog into agent-usable metadata.

## Derived Metadata

For each operation, the engine can derive:

- `canonical_action`: `search`, `read`, `create`, `update`, `delete`, `action`, or `unknown`
- `primary_resource`: the main business/resource concept
- `path_module`: the stable path/module cluster
- `result_shape`: `single`, `list`, `count`, `mutation`, or `unknown`
- `semantic_confidence` and `semantic_evidence`

## Contract Metadata

The OpenAPI contract extraction keeps:

- path/query/header/cookie parameters
- request body fields
- response fields
- content types
- security requirements
- response envelope candidates

This gives search and planning a deterministic base before LLM reasoning starts.

