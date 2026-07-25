---
title: Middleware
description: Use middleware to patch or filter model tool calls without changing application code deeply.
---

# Middleware

Middleware integrations can intercept tool selection or tool catalog construction
and apply graph-tool-call retrieval before model invocation.

## Adapter Boundary

Middleware should remain thin. It should delegate ranking, selection, and
diagnostics to the engine, while the host application keeps auth, session, and
execution state.

## Related Pages

- [Target Selection](../search/target-selection.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
