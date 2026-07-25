---
title: Middleware
description: application code를 크게 바꾸지 않고 model tool call을 patch/filter합니다.
---

# Middleware

Middleware integration은 model invocation 전에 tool selection 또는 tool catalog
construction을 intercept해서 graph-tool-call retrieval을 적용할 수 있습니다.

## Adapter Boundary

Middleware는 얇게 유지합니다. ranking, selection, diagnostics는 engine에 맡기고,
auth, session, execution state는 host application이 유지합니다.

## 관련 문서

- [Target Selection](../search/target-selection.md)
- [Failure Taxonomy](../plan/failure-taxonomy.md)
