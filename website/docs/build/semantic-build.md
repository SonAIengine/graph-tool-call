---
title: Semantic Build
description: Derive deterministic action, resource, module, and result-shape metadata from raw tool definitions.
---

# Semantic Build

Semantic build enriches raw tool schemas with deterministic metadata that search
and target selection can use.

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

## Quality Checks

Track these rates after a build:

- action known rate
- resource assigned rate
- module assigned rate
- result shape known rate
- unknown samples

## Related Pages

- [Target Selection](../search/target-selection.md)
- [XGEN Scale Gates](../validation/xgen-scale-gates.md)
