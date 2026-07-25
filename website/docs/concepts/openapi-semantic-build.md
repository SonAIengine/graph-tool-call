---
title: OpenAPI Semantic Build
description: Deterministically derive action, resource, module, shape, and contract metadata from raw OpenAPI operations.
---

# OpenAPI Semantic Build

OpenAPI specs often contain hundreds or thousands of operations with inconsistent
operation IDs, tags, summaries, schemas, and response envelopes. The semantic
build pass turns that raw catalog into agent-usable metadata.

The pass is deterministic by default. It should make the graph easier to search
and inspect before any LLM enrichment is involved.

## Why It Exists

Large enterprise specs often produce poor raw tool catalogs:

- many operations have generic names
- summaries mix business prose, release notes, and HTML fragments
- tags are missing or too broad
- list/detail/count operations look like siblings
- response envelopes hide the useful body fields

Semantic build creates stable fields that retrieval and target selection can
use directly.

## Derived Metadata

For each operation, the engine can derive:

- `canonical_action`: `search`, `read`, `create`, `update`, `delete`, `action`, or `unknown`
- `primary_resource`: the main business/resource concept
- `path_module`: the stable path/module cluster
- `result_shape`: `single`, `list`, `count`, `mutation`, or `unknown`
- `semantic_confidence` and `semantic_evidence`

## Derivation Priority

| Field | Priority |
| --- | --- |
| action | existing metadata, operationId verb, summary/description verb, HTTP method |
| resource | existing metadata, tag, stable path segment, operationId noun, schema/ref fields |
| module | stable path/module segment, operation group, source label |
| shape | operationId/summary hints, response schema shape, mutation method |

Existing human-edited metadata should not be overwritten unless the caller asks
for overwrite behavior.

## Contract Metadata

The OpenAPI contract extraction keeps:

- path/query/header/cookie parameters
- request body fields
- response fields
- content types
- security requirements
- response envelope candidates

This gives search and planning a deterministic base before LLM reasoning starts.

## What It Produces

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

## Quality Signals

Track coverage in the artifact summary:

- canonical action known rate
- primary resource assigned rate
- path/module assigned rate
- result shape known rate
- unknown samples
- weak edge evidence count

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| many `unknown` actions | operation ids and summaries are weak | add generic action aliases |
| many `unassigned` resources | tags/path segments are too broad | add resource aliases or source grouping |
| one huge module cluster | path module derivation is too coarse | inspect `path_module` rules |
| list/detail tools tie | missing `result_shape` | improve schema/summary hints |
| graph has too many weak edges | structural edges are being overused | filter visual/execution edges by evidence |

## Related Pages

- [Semantic Build](../build/semantic-build.md)
- [OpenAPI Collections](../guides/openapi-collections.md)
- [Search Tuning](../search/search-tuning.md)
