---
title: Retrieval 신호
description: graph-tool-call 검색 결과에 영향을 주는 ranking evidence를 설명합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Retrieval 신호

Retrieval은 설명 가능해야 합니다. candidate는 prompt가 우연히 선호해서가 아니라,
이름 붙은 signal 때문에 이겨야 합니다.

signal은 두 곳에서 사용됩니다.

- LLM이 tool을 보기 전에 compact candidate set을 ranking
- target selector가 candidate를 신뢰하거나 거절한 이유 설명

## Signal Pipeline

retrieval 경로는 inspect 가능한 단계로 나뉩니다. adapter는 prompt, secret, full API
payload를 저장하지 않고도 각 단계를 compact evidence로 남길 수 있습니다.

| Stage | Input | Output | Debug Object |
| --- | --- | --- | --- |
| Query normalization | user query | token, alias, inferred shape | `seeds` |
| Candidate retrieval | indexed tool text와 metadata | ranked tool | `score_breakdown` |
| Contract matching | request/response field | consumes/produces match | `semantic_evidence.contract_match` |
| Graph expansion | deterministic/promoted edge | producer/neighbor tool | `expanded_from`, `edge_evidence` |
| Selector handoff | Top-K candidate | selector-ready ranking row | `semantic_evidence` |

즉 retrieval은 prompt heuristic이 아니라 query engine에 가깝습니다. 각 candidate가 어떤
artifact 때문에 보였는지 설명할 수 있어야 합니다.

## Core Signals

| Signal | Source | 중요한 이유 |
| --- | --- | --- |
| `seed` | tool name, operation id, summary, description | 직접 retrieval seed contribution을 기록 |
| `action_match` | `metadata.ai_metadata.canonical_action` | search/read/create/update/delete intent 분리 |
| `resource_match` | `metadata.ai_metadata.primary_resource` | business object를 맞춤 |
| `module_match` | `metadata.openapi.path_module` 또는 operation group | 대형 enterprise API 범위를 좁힘 |
| `shape_match` | `metadata.ai_metadata.result_shape` | list/detail/count/mutation sibling 구분 |
| `contract_match` | request/response contract field | 사용자 entity와 field evidence가 맞는지 확인 |
| `graph_expansion` | producer, consumer, manual, trace, curated edge | workflow 주변 tool을 후보에 포함 |
| `learning` | promoted trace-learning suggestion | 검증된 local feedback을 low-weight boost로 반영 |

## Evidence Output

signal detail은 `include_evidence=True`로 확인합니다.

<Tabs>
  <TabItem value="graphify" label="Graphify" default>

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    "환불 가능한 주문을 찾아줘",
    top_k=5,
    include_evidence=True,
)

for row in response["results"]:
    print(row["name"], row["score_breakdown"])
```

  </TabItem>
  <TabItem value="toolgraph" label="ToolGraph">

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
rows = graph.retrieve_with_scores(
    "환불 가능한 주문을 찾아줘",
    top_k=5,
)

for row in rows:
    print(row.tool.name, row.score)
```

  </TabItem>
  <TabItem value="cli" label="CLI">

```bash
graph-tool-call search "환불 가능한 주문을 찾아줘" \
  --source openapi.json \
  --top-k 5 \
  --scores
```

  </TabItem>
</Tabs>

일반적인 output은 다음과 같습니다.

```json
{
  "name": "getRefundableOrderList",
  "score_breakdown": {
    "seed": 0.0314,
    "graph": 0.0057,
    "learning": 0.02,
    "history_demoted": false,
    "action_match": 1.0,
    "resource_match": 1.0,
    "module_match": 0.0,
    "shape_match": 1.0,
    "contract_match": 1.0,
    "graph_expansion": 0.1
  },
  "semantic_evidence": {
    "canonical_action": "search",
    "primary_resource": "order",
    "result_shape": "list",
    "action_match": true,
    "resource_match": true,
    "shape_match": true,
    "contract_match": true,
    "matched_terms": ["order", "refund"]
  }
}
```

숫자의 절대 scale은 engine version에 따라 바뀔 수 있습니다. 안정 contract는 고정된 절대
score가 아니라 이름 붙은 signal과 evidence field가 남는 것입니다.

## Result Row 읽기

weight를 바꾸기 전에 result row부터 읽습니다. 대부분의 search 실패는 score 상수 하나가
아니라 metadata나 contract 누락에서 시작합니다.

| Field | 확인할 질문 |
| --- | --- |
| `name` | 기대 tool이 Top-K에 들어왔는가? |
| list position | tool이 너무 낮은가, 아예 없는가? |
| `score_breakdown.seed` | name, summary, operation id가 candidate를 seed했는가? |
| `score_breakdown.action_match` | query 동사가 `canonical_action`과 맞았는가? |
| `score_breakdown.resource_match` | business object가 `primary_resource`와 맞았는가? |
| `score_breakdown.shape_match` | list/detail/count/mutation intent가 `result_shape`와 맞았는가? |
| `semantic_evidence.contract_match` | request/response field가 query와 맞았는가? |
| `edge_evidence` | graph relation 때문에 candidate가 추가됐는가? |
| `stats.token_budget_used` | retrieval context가 LLM에 너무 많이 넘어가는가? |

기대 tool이 없으면 ingest, semantic metadata, alias, contract extraction을 고칩니다. 기대
tool은 있는데 LLM이 sibling을 고르면 [Target Selection](./target-selection.md)을
확인합니다.

## Signal Interaction

| 상황 | 유용한 signal |
| --- | --- |
| 한국어 query, 영어 operation id | keyword, alias, Korean tokenizer, semantic metadata |
| list/detail sibling conflict | `shape_match`, response schema, operation id hint |
| 직접 검색되지 않은 tool | `graph_expansion`, producer/consumer edge |
| LLM이 틀린 target 선택 | selector `rank_signals`와 retrieval evidence |
| 반복 성공한 correction | promoted `learning` suggestion |

## 예시: List vs Detail Sibling

대형 OpenAPI catalog에는 단어 하나만 다른 sibling operation이 자주 있습니다. selector가
도움을 주려면 retrieval이 두 candidate의 evidence를 보존해야 합니다.

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.load("collection.json")
response = retrieve_graphify(
    graph,
    "회원 배송지 상세 정보를 조회해줘",
    top_k=8,
    include_evidence=True,
)

for row in response["results"]:
    print(
        row["name"],
        row["score_breakdown"].get("shape_match"),
        row["semantic_evidence"].get("matched_terms"),
    )
```

기대 동작:

| Candidate | 좋은 Evidence |
| --- | --- |
| `getMemberDeliveryDetail` | `read`, `member_delivery`, `single`, response field |
| `getMemberDeliveryList` | `read`, `member_delivery`, `list`, 더 약한 shape match |
| `getMemberInfo` | `read`, `member`, 부분 resource match |

모든 candidate가 동일하게 보이면 search weight보다 `result_shape`, `primary_resource`,
response contract coverage를 먼저 보강합니다.

## Tuning 원칙

weight를 바꾸기 전에 metadata와 contract를 먼저 개선합니다.

1. expected tool이 Top-K에 있는지 확인합니다.
2. `score_breakdown`과 `semantic_evidence`를 봅니다.
3. text가 약하면 summary 또는 alias를 개선합니다.
4. list/detail이 헷갈리면 `result_shape`를 개선합니다.
5. upstream value가 필요하면 contract producer를 확인합니다.
6. evidence가 올바른 뒤에만 weight를 조정합니다.

## Signal Quality Checklist

collection rebuild나 새 source 추가 시 아래를 확인합니다.

| Check | 건강한 신호 |
| --- | --- |
| action coverage | 대부분 tool에 알려진 `canonical_action`이 있음 |
| resource coverage | tool이 안정적인 `primary_resource`로 배정됨 |
| module coverage | 큰 API가 path/module group으로 나뉨 |
| contract coverage | request/response field가 `api_contract`에 보존됨 |
| evidence density | Top-K row에 semantic 또는 contract signal이 있음 |
| expansion restraint | graph expansion이 candidate를 범람시키지 않고 producer를 추가함 |
| learning restraint | promoted suggestion만 ranking에 영향 |

이 체크는 product diagnostic과 release gate에 보여야 합니다. search, selector, plan,
adapter execution 중 어디가 문제인지 가장 빠르게 가르는 기준이 됩니다.

## Best Practice

product debug screen과 regression fixture에는 `include_evidence=True`를 사용합니다. ranking을
설명하는 compact evidence만 저장하고 raw secret이나 full API payload는 저장하지 않습니다.

production log에 저장할 수 있는 항목은 다음 정도입니다.

- tool name
- rank
- score breakdown
- selected evidence key
- token budget used
- learning suggestion id

저장하면 안 되는 항목은 다음입니다.

- full request/response body
- auth header
- cookie
- user identifier
- secret을 포함할 수 있는 raw prompt trace

## Adapter Display Contract

product UI에서 retrieval diagnostic을 보여줄 때는 raw metadata dump가 아니라 compact
comparison으로 보여줍니다.

| UI Field | Source |
| --- | --- |
| rank와 tool name | result row |
| action/resource/shape badge | `semantic_evidence.action_match`, `resource_match`, `shape_match` |
| matched term | `semantic_evidence.matched_terms` |
| Top-K에 들어온 이유 | `stats.seeds`, `expanded_from` |
| selection outcome | `target_selector.selected_target` |
| uncertainty | `ambiguous`, `reason_codes` |

collection에 수백, 수천 개 tool이 있어도 debugging 가능한 형태를 유지해야 합니다.

## 검증

scoring 또는 metadata extraction을 바꾸면 retrieval-focused test를 실행합니다.

```bash
poetry run pytest tests/test_graphify_metadata.py tests/test_graphify_contract_025.py -q
```

## 관련 문서

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Search Tuning](./search-tuning.md)
