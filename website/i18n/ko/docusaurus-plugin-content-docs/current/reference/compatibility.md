---
title: 호환성
description: public contract, additive change, adapter-safe import path를 설명합니다.
---

# 호환성

Adapter는 문서화된 public API와 additive artifact field에 의존해야 합니다.

## Stable Import Policy

아래 import를 우선합니다.

- `graph_tool_call`
- `graph_tool_call.graphify`
- `graph_tool_call.plan`
- `graph_tool_call.learning`
- `graph_tool_call.analyze`

reference page에서 stable이라고 명시하지 않은 internal module private helper import는
피합니다.

## Artifact Policy

새 artifact field는 additive여야 합니다. migration guide가 없는 한 기존 graph
version은 계속 읽을 수 있어야 합니다.

## 관련 문서

- [Public API](./public-api.md)
- [Artifact Schemas](./artifact-schemas.md)
