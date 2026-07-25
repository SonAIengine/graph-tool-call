---
title: 한글 검색
description: product-specific term을 하드코딩하지 않고 한국어/영어가 섞인 tool catalog를 검색합니다.
---

# 한글 검색

많은 enterprise catalog는 한국어 summary와 영어 operation id, field name이 섞여
있습니다. graph-tool-call은 human description과 stable technical metadata를 함께
index합니다.

목표는 한국어 business term을 engine에 하드코딩하는 것이 아닙니다. 엔진은
product-neutral metadata를 만들고, adapter가 필요한 alias를 option으로 전달합니다.

## 설치

한국어 비중이 큰 catalog에는 Korean extra를 사용합니다.

```bash
pip install "graph-tool-call[korean]"
```

이 extra가 없어도 동작하지만, 한영 혼합 query에서는 operation id, path segment,
semantic metadata 의존도가 더 커질 수 있습니다.

## Minimal Example

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")

ko = graph.retrieve_with_scores("회원 상세 조회", top_k=8)
en = graph.retrieve_with_scores("member detail info", top_k=8)

print([item.tool.name for item in ko[:3]])
print([item.tool.name for item in en[:3]])
```

catalog에 충분한 semantic/contract evidence가 있으면 두 query는 같은 target family를
반환해야 합니다.

## 도움이 되는 것

- 가능한 경우 Korean tokenizer extra
- 영어 operation id
- path segment
- deterministic action/resource metadata
- request/response field name
- adapter가 option으로 전달한 alias dictionary

## Alias Policy

Alias는 adapter 또는 collection configuration에서 전달합니다.

```python
semantic_options = {
    "resource_aliases": {
        "회원": "member",
        "주문": "order",
    },
    "action_aliases": {
        "조회": "search",
        "상세": "read",
    },
}
```

XGEN, BO, 특정 도메인 사전은 library에 직접 넣지 않습니다.

## Query Patterns

| User Query | 기대 signal |
| --- | --- |
| `회원 상세 조회` | `primary_resource=member`, `result_shape=single` |
| `주문 목록 검색` | `primary_resource=order`, `canonical_action=search`, `result_shape=list` |
| `쿠폰 개수` | `result_shape=count` |
| `claim cancel reason` | English operation/path token과 resource/action metadata |

## Failure Modes

| 증상 | 가능한 원인 | 확인할 것 |
| --- | --- | --- |
| 한국어 query가 generic tool만 맞춤 | summary가 noisy하거나 없음 | `one_line_summary`, `when_to_use` |
| 영어 operation id가 한국어 의도보다 강함 | action/resource alias 부족 | semantic option과 metadata |
| 상세 query가 목록 tool을 반환 | `result_shape` 부족 | semantic build output |
| 모든 query가 같은 module을 맞춤 | path/module cluster가 너무 큼 | `path_module`, readiness report |

## Validation

같은 target family에 대해 한국어/영어 pair case를 유지합니다.

```json
[
  {"query": "회원 상세 조회", "expected": "getMemberDetail"},
  {"query": "member detail info", "expected": "getMemberDetail"}
]
```

Top-1, Top-3, Top-8, sibling mismatch rate를 추적합니다. Product validation에서는 miss마다
evidence output을 저장해 prompt가 아니라 metadata, alias, contract extraction 중 어느
것을 고쳐야 하는지 판단합니다.

## 관련 문서

- [Semantic Build](../build/semantic-build.md)
- [Retrieval Signals](./retrieval-signals.md)
- [Search Tuning](./search-tuning.md)
