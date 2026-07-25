---
title: 도구 그래프
description: retrieval, candidate expansion, planning, visualization, trace learning을 가능하게 하는 graph data model입니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# 도구 그래프

도구 그래프는 대형 tool catalog와 LLM agent 사이에 놓이는 evidence layer입니다.
tool은 node로 저장하고, 관계는 edge로 저장하며, metadata에는 retrieval, target
selection, planning, product UI가 “왜 이 tool을 찾았는지” 설명하는 근거가
들어갑니다.

그래프는 먼저 그림이 아닙니다. contract를 가진 검색 구조입니다. visualization은
그래프의 한 consumer일 뿐이고, 핵심 목적은 큰 catalog를 작고 정렬된, 검증 가능한
candidate set으로 줄이는 것입니다.

## 그래프가 저장하는 것

```text
OpenAPI / MCP / Python tools
        |
        v
ToolSchema nodes
api_contract
semantic metadata
        |
        v
evidence edges
readiness reports
quality summaries
        |
        v
retrieval
target selection
plan synthesis
runner events
learning
```

좋은 graph artifact는 다섯 가지 질문에 답해야 합니다.

1. 각 tool은 무엇을 하는가?
2. 실행에 어떤 request field가 필요한가?
3. response에서 어떤 field를 만들 수 있는가?
4. 어떤 tool들이 신뢰 가능한 근거로 연결되어 있는가?
5. 어떤 부분이 약하거나, 빠졌거나, 실행하기 위험한가?

## 최소 Build

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
graph-tool-call \
  build-openapi-collection \
  openapi.json \
  -o artifact.json
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
)

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)

print(artifact["semantic_summary"])
print(artifact["edge_quality_summary"])
```

  </TabItem>
  <TabItem value="inspect-node" label="Node">

```python
tool = next(iter(artifact["tools"].values()))

print(tool["name"])
print(tool["metadata"]["openapi"])
print(tool["metadata"]["ai_metadata"])
print(tool["metadata"]["api_contract"])
```

  </TabItem>
  <TabItem value="inspect-edge" label="Edge">

```python
edge = artifact["graph"]["edges"][0]

print(edge["source"], "->", edge["target"])
print(edge["relation"])
print(edge["evidence_sources"])
print(edge.get("data_flow"))
```

  </TabItem>
</Tabs>

product integration에서는 graph payload만 저장하지 말고 전체 artifact를 저장하는 것을
권장합니다. summary와 readiness section이 있어야 build 결과를 관측할 수 있습니다.

## Node Model

각 tool node는 `ToolSchema`에서 시작합니다. node에는 source fact, semantic fact,
IO contract, execution readiness fact가 함께 들어갈 수 있습니다.

| 영역 | 대표 필드 | 필요한 이유 |
| --- | --- | --- |
| Identity | `name`, `description`, `tags`, `source` | 기본 catalog identity와 keyword search |
| OpenAPI | `method`, `path`, `operation_id`, `parameters`, `security` | request 구성과 auth diagnostics |
| Semantics | `canonical_action`, `primary_resource`, `path_module`, `result_shape` | retrieval과 target selection의 action/resource/shape matching |
| Contract | `api_contract.consumes`, `api_contract.produces`, `api_contract.links` | producer expansion과 plan synthesis |
| Readiness | response/request coverage, enum/context/auth fields | build warning과 execute preflight |
| Learning | promoted target preference와 plan path | 검증된 trace에서 얻은 low-weight ranking improvement |

좋은 node는 compact해야 합니다. OpenAPI의 모든 raw leaf를 ranking text로 밀어 넣는 것이
아니라, engine이 “이 tool이 맞는 candidate인가”를 판단하는 데 필요한 field를 저장합니다.

## Semantic Metadata

Semantic metadata는 기본적으로 deterministic하게 만들어집니다. OpenAPI semantic pass는
LLM을 호출하지 않고 검색에 중요한 field를 추출합니다.

| Field | 예시 | 추출 근거 |
| --- | --- | --- |
| `canonical_action` | `search`, `read`, `create`, `update`, `delete`, `action` | operation id, HTTP method, summary, description |
| `primary_resource` | `order`, `customer`, `payment` | tag, 안정적인 path segment, operation noun, schema |
| `path_module` | `/api/v1/orders` | 안정적인 path prefix |
| `operation_group` | `orders` | tag 또는 grouped path/module fact |
| `result_shape` | `single`, `list`, `count`, `mutation` | method, name, description, response schema |
| `semantic_confidence` | `high`, `medium`, `low` | evidence strength |

adapter는 resource, action, module, context, paging, search field alias를 옵션으로
전달할 수 있습니다. library 내부에 특정 고객사의 business dictionary를 하드코딩하지
않는 것이 원칙입니다.

## IO Contract

IO contract는 API schema를 planning evidence로 바꿉니다.

| Contract Field | 의미 |
| --- | --- |
| `consumes` | path, query, header, cookie, body에서 tool이 필요로 하는 field |
| `produces` | response body 또는 envelope에서 tool이 반환할 수 있는 field |
| `links` | 명시적 또는 추론된 producer-consumer 관계 |
| `kind` | `data`, `context`, `auth` |
| `required` | 값이 없으면 실행을 막아야 하는지 |
| `enum` | source가 제공한 허용 값 |
| `semantic_tag` | paging, search filter, id, date, auth 같은 generic role |

Contract field는 search와 execution 사이의 다리입니다. query는 text로 tool을 찾을 수
있지만, plan은 required input이 채워지거나 이전 step에서 생산될 수 있을 때만 실행할 수
있습니다.

## Edge Model

Edge는 어떤 tool들을 함께 고려해야 하는지 설명합니다. graphify-style edge는
`normalize_graph_edge()`로 정규화하고 `merge_graph_edges()`로 병합할 수 있습니다.

| Edge Source | 대표 Relation | 강도 | 사용처 |
| --- | --- | --- | --- |
| Structural | 같은 source, tag, module, path | 약함 | navigation, grouping, map view |
| Name-based | 비슷한 operation name 또는 resource | 약함-중간 | candidate expansion, diagnostics |
| API contract | produced field가 consumed field를 만족 | 강함 | producer expansion, plan synthesis |
| OpenAPI link | OpenAPI에 명시된 관계 | 강함 | plan synthesis와 explainability |
| Manual | 운영자가 curated한 관계 | 강함 | product-specific graph correction |
| Run observed | 성공 plan binding에서 관찰된 관계 | promote 전에는 suggestion | trace learning과 ranking hint |
| LLM curated | offline enrichment 또는 curation | 검증 전에는 중간 | semantic grouping |

정규화된 edge는 다음 정보를 갖습니다.

```json
{
  "source": "searchOrders",
  "target": "getOrderDetail",
  "relation": "requires",
  "kind": "data",
  "confidence": "INFERRED",
  "conf_score": 0.92,
  "evidence": "produces orderId consumed by getOrderDetail",
  "evidence_sources": ["api_contract"],
  "data_flow": {"from_path": "items[].orderId", "to_field": "orderId"},
  "is_manual": false
}
```

dense structural edge를 execution proof로 취급하면 안 됩니다. planning에는 contract,
OpenAPI link, manual, promoted trace evidence를 우선해야 합니다.

## Search Path

```text
query
  -> keyword and tokenizer seeds
  -> semantic/action/resource/shape scoring
  -> contract scoring
  -> reliable edge 기반 graph expansion
  -> evidence가 포함된 ranked candidates
```

<Tabs>
  <TabItem value="retrieve" label="검색" default>

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    artifact["graph"],
    query="환불 가능한 주문을 찾아줘",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["tool_name"])
print(first["score_breakdown"])
print(first["candidate_evidence"])
```

  </TabItem>
  <TabItem value="selector" label="선택">

```python
from graph_tool_call.graphify import (
    select_target_candidate,
)

selection = select_target_candidate(
    query="환불 가능한 주문을 찾아줘",
    candidates=[
        item["tool_name"]
        for item in response["results"]
    ],
    tools=artifact["tools"],
    retrieval_results=response["results"],
    llm_target=llm_intent.target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
```

  </TabItem>
</Tabs>

LLM에는 전체 source file이 아니라 필요한 만큼 작은 catalog만 전달해야 합니다. LLM이
약한 target을 골랐고 deterministic evidence가 다른 candidate를 강하게 지지하면 selector가
override를 기록할 수 있습니다. margin이 약하면 조용히 고치지 말고 ambiguity를
diagnostics로 남겨야 합니다.

## Planning Path

Planning은 target selection 이후 그래프를 사용합니다. `PathSynthesizer`는
producer-consumer evidence, required field, enum requirement, context default, user input
slot을 확인할 수 있습니다.

```text
selected target
  -> required consumes fields
  -> available context/defaults/user input
  -> data-flow edge 기반 producer expansion
  -> executable Plan
  -> PlanRunner.run_stream() events
```

실패는 구조화되어야 합니다. request field 누락, enum 선택 필요, ambiguous target, auth
preflight 실패, HTTP 4xx, HTTP 5xx는 서로 다른 조건이므로 서로 다른 reason code로
표현해야 합니다.

## 대형 Graph Visualization

대형 API catalog는 모든 node와 edge를 한 번에 렌더링하면 안 됩니다. 600개 tool과
수천 개 structural relationship을 하나의 force-directed graph로 그리면 읽을 수 없는 화면이
됩니다.

세 가지 view를 권장합니다.

| View | 목적 | 렌더링 대상 |
| --- | --- | --- |
| Map view | collection 구조 이해 | module, resource, action, orphan count, readiness |
| Scoped graph | 선택한 module/resource/target 검사 | 선택 범위의 neighborhood와 high-value edge |
| Workflow path | 하나의 retrieval 또는 plan 결정 설명 | target, producer, required field, selected edge |

visual edge는 high-signal evidence부터 보여주는 것이 좋습니다.

- API contract data flow
- explicit OpenAPI links
- manual edges
- promoted run-observed edges
- high-confidence semantic relationships

structural/name-based edge는 먼저 filter나 summary로 보여주고, 사용자가 scope를 좁힌 뒤에
렌더링하는 쪽이 낫습니다.

## Persistence And Rebuilds

artifact에는 version과 provenance metadata를 저장합니다.

```json
{
  "graph_tool_call_version": "0.32.1",
  "collection_graph_version": 2,
  "semantic_summary": {
    "canonical_action_known_rate": 0.96,
    "primary_resource_assigned_rate": 0.88
  },
  "edge_quality_summary": {
    "total": 14569,
    "api_contract": 830,
    "manual": 12,
    "run": 4
  }
}
```

rebuild 중에는 다음 정책을 지킵니다.

1. source-derived tool, semantic, contract, readiness, weak structural edge는 다시
   계산합니다.
2. curated `ai_metadata`, `context_defaults`, `enum_mappings`, manual edge, Quality Lab
   case, promoted learning suggestion 같은 product-owned field는 보존합니다.
3. artifact를 promote하기 전에 quality gate를 다시 실행합니다.

## 운영 체크리스트

adapter가 graph를 agent에 노출하기 전에 확인할 항목입니다.

- `semantic_summary`의 action/resource/module coverage가 충분히 높은가?
- `edge_quality_summary`에 contract 또는 curated evidence가 충분한가?
- `readiness_report`에 blocker issue가 없는가?
- 실행 전에 required auth/context field가 보이는가?
- search case의 Top-K와 Top-1 결과가 안정적인가?
- plan case가 missing field와 auth failure reason code를 보존하는가?
- 대형 catalog visualization이 map 또는 scoped view를 기본으로 쓰는가?
- trace learning이 scrubbed evidence만 저장하고 suggestion을 보수적으로 promote하는가?

## 관련 문서

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Collection Artifacts](../build/collection-artifacts.md)
- [IO Contracts](../build/io-contracts.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Runner Events](../plan/runner-events.md)
- [Trace Learning](./trace-learning.md)
