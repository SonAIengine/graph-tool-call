---
title: Compatibility
description: Understand public contracts, additive changes, and adapter-safe import paths.
---

# Compatibility

Adapters should depend on documented public APIs and additive artifact fields.
This page defines the compatibility posture for application code that embeds
graph-tool-call.

## Stable Import Policy

Prefer imports from:

- `graph_tool_call`
- `graph_tool_call.graphify`
- `graph_tool_call.plan`
- `graph_tool_call.learning`
- `graph_tool_call.analyze`

Avoid importing private helpers from internal modules unless a reference page
explicitly marks them as stable.

## Public Surface

| Area | Stable Entry Point |
| --- | --- |
| package facade | `graph_tool_call.ToolGraph`, `ToolSchema`, `parse_tool` |
| graph artifacts | `graph_tool_call.graphify` documented helpers |
| planning | `graph_tool_call.plan` schemas and runner APIs |
| learning | `graph_tool_call.learning` record and suggestion helpers |
| diagnostics | `graph_tool_call.analyze` reports |

Submodules beneath those packages may still contain private implementation
helpers. Treat a helper as stable only when the reference documentation says so.

## Artifact Policy

New artifact fields should be additive. Existing graph versions should remain
readable unless a migration guide says otherwise.

Adapter rules:

- preserve unknown fields in collection artifacts
- do not assume dictionaries contain only the fields documented today
- tolerate missing optional fields from older artifacts
- pin package versions exactly in production deployments
- keep product-specific DB/auth/UI state outside engine artifacts

## Versioning Expectations

Patch versions should not intentionally break documented imports or schema
fields. Minor versions may add public helpers, additive schema fields, reason
codes, and diagnostics. Breaking changes require a migration note.

| Change Type | Compatibility Expectation |
| --- | --- |
| new result field | additive, adapters should preserve it |
| new reason code | additive, UI should show unknown codes generically |
| new optional parameter | additive, defaults preserve behavior |
| renamed public import | breaking, requires migration note |
| removed artifact field | breaking, avoid without migration |

## Adapter-Safe Patterns

Use documented imports:

```python
from graph_tool_call.graphify import retrieve_graphify
from graph_tool_call.plan import PlanRunner
from graph_tool_call.learning import build_trace_learning_record
```

Avoid private implementation imports:

```python
# Avoid depending on implementation modules unless documented.
from graph_tool_call.graphify.retrieval import _select_seeds
```

## Release Checks

Before upgrading graph-tool-call in a product adapter:

1. run import smoke tests for public imports
2. rebuild one representative collection artifact
3. run search and plan Quality Lab cases
4. verify event and report schemas are still accepted
5. verify unknown fields are preserved on save/rebuild

## Related Pages

- [Public API](./public-api.md)
- [Artifact Schemas](./artifact-schemas.md)
- [Event Schemas](./event-schemas.md)
- [Release Gates](../validation/release-gates.md)
