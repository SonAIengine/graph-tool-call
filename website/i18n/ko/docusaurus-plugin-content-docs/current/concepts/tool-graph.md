---
title: 도구 그래프
description: retrieval, candidate expansion, planning, trace learning을 가능하게 하는 graph data model입니다.
---

# 도구 그래프

도구 그래프는 핵심 데이터 구조입니다. 각 tool은 metadata를 가진 node이고,
edge는 retrieval과 planning에 필요한 관계를 설명합니다.

## Node Signal

Tool node에는 다음 정보가 들어갈 수 있습니다.

- name, description, tag, source metadata
- OpenAPI method/path/operation metadata
- canonical action, primary resource, module, result shape 같은 semantic metadata
- consumed/produced field에 대한 IO contract
- execution/auth readiness 정보

## Edge Signal

Edge는 다음 출처에서 생깁니다.

- OpenAPI 구조
- request/response data-flow contract
- semantic relation inference
- manual curation
- run-observed trace evidence

Graph edge는 시각화용 장식이 아닙니다. candidate expansion, workflow discovery,
target selection diagnostics에 직접 사용됩니다.

## Edge Kind

| Edge Kind | 의미 | 사용처 |
| --- | --- | --- |
| structural | 같은 source, tag, module, path 관계 | navigation과 약한 grouping |
| data flow | 한 tool이 만든 field를 다른 tool이 소비 | plan synthesis와 producer expansion |
| semantic | action/resource 유사성 또는 curated relation | retrieval과 target selection |
| manual | 사람이 제공한 relation | high-trust graph evidence |
| trace | 성공/실패 run에서 관찰된 관계 | learning과 future ranking |

dense structural edge를 강한 execution evidence로 취급하면 안 됩니다. planning에는 contract,
manual, OpenAPI link, promoted trace edge를 우선합니다.

## Retrieval 흐름

```text
query -> keyword seeds -> semantic/contract scoring -> graph expansion -> ranked candidates
```

LLM에는 전체 tool catalog가 아니라 가장 강한 작은 후보 집합이 전달되어야 합니다.

## 대형 Graph Visualization

대형 API graph는 모든 node와 edge를 한 번에 렌더링하면 안 됩니다. 유용한 product UI는
보통 두 가지 mode가 필요합니다.

- **map mode**: module, resource, action, orphan count, readiness를 요약
- **scoped graph mode**: 선택된 module, target tool, workflow path를 자세히 표시

graph는 기본적으로 evidence structure입니다. 시각화는 모든 관계를 한 화면에 그리는
것이 아니라, 사용자가 scope를 고르고 candidate가 왜 연결됐는지 이해하게 해야 합니다.

## Persistence

graph artifact에는 version metadata를 저장합니다.

```json
{
  "graph_tool_call_version": "0.32.1",
  "collection_graph_version": 2,
  "nodes": 624,
  "edges": 14569
}
```

rebuild 중에는 manual edge와 promoted learning edge를 보존합니다. 약한 structural edge는
source에서 다시 계산합니다.

## 관련 문서

- [Collection Artifacts](../build/collection-artifacts.md)
- [Candidate Expansion](../search/candidate-expansion.md)
- [Trace Learning](./trace-learning.md)
