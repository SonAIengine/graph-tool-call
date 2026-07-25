---
title: Semantic Build
description: Derive deterministic action, resource, module, and result-shape metadata from raw tool definitions.
---

# Semantic Build

Semantic build enriches raw tool schemas with deterministic metadata that search
and target selection can use.

Run semantic build during OpenAPI collection builds so large specs do not remain
as anonymous `unknown` actions or `unassigned` resources.

## Generated Metadata

| Field | Meaning |
| --- | --- |
| `canonical_action` | `search`, `read`, `create`, `update`, `delete`, `action`, or `unknown` |
| `primary_resource` | The main resource the operation is about |
| `path_module` | Stable module or route grouping from the path |
| `operation_group` | Higher-level operation grouping |
| `result_shape` | `single`, `list`, `count`, `mutation`, or `unknown` |
| `semantic_confidence` | Deterministic confidence signal |
| `semantic_evidence` | Sources that explain the metadata |

## Priority Rules

The engine prefers existing curated metadata first. If metadata is absent, it
uses operation id, summary, description, HTTP method, path segments, tags,
schema references, and identifier fields.

Product-specific dictionaries should be passed as options. They should not be
hard-coded into the library.

## Minimal Example

```python
from graph_tool_call.graphify.semantics import annotate_openapi_tool_semantics

tools = annotate_openapi_tool_semantics(
    tools,
    options={
        "resource_aliases": {"member": ["customer", "user"]},
        "action_aliases": {"search": ["find", "lookup"]},
        "module_aliases": {"orders": ["claim", "refund"]},
    },
    overwrite=False,
)
```

`overwrite=False` preserves operator-curated metadata. Use overwrite only when
you intentionally want to rebuild semantic fields from source.

## Artifact Summary

Collection artifacts should expose semantic coverage:

```json
{
  "semantic_summary": {
    "canonical_action_known_rate": 0.96,
    "primary_resource_assigned_rate": 0.82,
    "path_module_assigned_rate": 0.99,
    "result_shape_known_rate": 0.74,
    "unknown_samples": ["legacyAction", "executeProc"]
  }
}
```

Low rates are not cosmetic. They directly affect search ranking, target
selection, and graph visualization.

## Quality Checks

Track these rates after a build:

- action known rate
- resource assigned rate
- module assigned rate
- result shape known rate
- unknown samples

## Failure Modes

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| many `unknown` actions | weak operation ids and summaries | pass action aliases or curate metadata |
| many unassigned resources | broad tags or generic path names | pass resource aliases or inspect path modules |
| one module contains most tools | module derivation too coarse | adjust module aliasing or source grouping |
| detail queries choose list tools | `result_shape` missing or wrong | improve schema and summary hints |

## Related Pages

- [Target Selection](../search/target-selection.md)
- [OpenAPI Semantic Build](../concepts/openapi-semantic-build.md)
- [XGEN Scale Gates](../validation/xgen-scale-gates.md)
