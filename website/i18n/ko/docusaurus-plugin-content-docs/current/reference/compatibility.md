---
title: 호환성
description: public contract, additive change, adapter-safe import path를 설명합니다.
---

# 호환성

Adapter는 문서화된 public API와 additive artifact field에 의존해야 합니다.
이 페이지는 graph-tool-call을 embedding하는 application code의 compatibility 기준을
정의합니다.

## Stable Import Policy

아래 import를 우선합니다.

- `graph_tool_call`
- `graph_tool_call.graphify`
- `graph_tool_call.plan`
- `graph_tool_call.learning`
- `graph_tool_call.analyze`

reference page에서 stable이라고 명시하지 않은 internal module private helper import는
피합니다.

## Public Surface

| Area | Stable Entry Point |
| --- | --- |
| package facade | `graph_tool_call.ToolGraph`, `ToolSchema`, `parse_tool` |
| graph artifacts | `graph_tool_call.graphify`의 문서화된 helper |
| planning | `graph_tool_call.plan` schema와 runner API |
| learning | `graph_tool_call.learning` record와 suggestion helper |
| diagnostics | `graph_tool_call.analyze` report |

해당 package 아래의 submodule에도 private implementation helper가 있을 수 있습니다.
reference 문서가 stable이라고 말하는 helper만 stable로 취급합니다.

## Artifact Policy

새 artifact field는 additive여야 합니다. migration guide가 없는 한 기존 graph
version은 계속 읽을 수 있어야 합니다.

Adapter rule:

- collection artifact의 unknown field를 보존합니다.
- dictionary가 오늘 문서화된 field만 가진다고 가정하지 않습니다.
- older artifact에서 optional field가 없을 수 있음을 허용합니다.
- production deployment에서는 package version을 exact pin합니다.
- product-specific DB/auth/UI state는 engine artifact 밖에 둡니다.

## Versioning Expectations

Patch version은 문서화된 import나 schema field를 의도적으로 깨지 않아야 합니다. Minor
version은 public helper, additive schema field, reason code, diagnostic을 추가할 수
있습니다. Breaking change에는 migration note가 필요합니다.

| Change Type | Compatibility Expectation |
| --- | --- |
| new result field | additive. adapter는 보존해야 함 |
| new reason code | additive. UI는 unknown code를 generic하게 보여야 함 |
| new optional parameter | additive. default가 기존 behavior 보존 |
| renamed public import | breaking. migration note 필요 |
| removed artifact field | breaking. migration 없이 피해야 함 |

## Adapter-Safe Patterns

문서화된 import를 사용합니다.

```python
from graph_tool_call.graphify import retrieve_graphify
from graph_tool_call.plan import PlanRunner
from graph_tool_call.learning import build_trace_learning_record
```

private implementation import는 피합니다.

```python
# 문서화되지 않았다면 의존하지 않습니다.
from graph_tool_call.graphify.retrieval import _select_seeds
```

## Release Checks

product adapter에서 graph-tool-call을 upgrade하기 전:

1. public import smoke test를 실행합니다.
2. 대표 collection artifact 1개를 rebuild합니다.
3. search와 plan Quality Lab case를 실행합니다.
4. event/report schema가 계속 수용되는지 확인합니다.
5. save/rebuild 과정에서 unknown field가 보존되는지 확인합니다.

## 관련 문서

- [Public API](./public-api.md)
- [Artifact Schemas](./artifact-schemas.md)
- [Event Schemas](./event-schemas.md)
- [Release Gates](../validation/release-gates.md)
