---
title: Compatibility
description: Understand public contracts, additive changes, and adapter-safe import paths.
---

# Compatibility

Adapters should depend on documented public APIs and additive artifact fields.

## Stable Import Policy

Prefer imports from:

- `graph_tool_call`
- `graph_tool_call.graphify`
- `graph_tool_call.plan`
- `graph_tool_call.learning`
- `graph_tool_call.analyze`

Avoid importing private helpers from internal modules unless a reference page
explicitly marks them as stable.

## Artifact Policy

New artifact fields should be additive. Existing graph versions should remain
readable unless a migration guide says otherwise.

## Related Pages

- [Public API](./public-api.md)
- [Artifact Schemas](./artifact-schemas.md)
