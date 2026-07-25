---
title: 검색 튜닝
description: alias, semantic metadata, contract, learning evidence, repeatable validation gate로 retrieval 품질을 개선합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# 검색 튜닝

Search tuning은 LLM prompt만을 진실의 원천으로 두지 않고 tool retrieval 품질을 개선하는
작업입니다. 먼저 catalog evidence를 고치고, 그다음 ranking policy를 보고, 마지막에
prompt를 조정합니다.

목표는 manual query 하나를 좋아 보이게 만드는 것이 아닙니다. named query suite가
재현 가능하고 review 가능하며 rollback 가능한 방식으로 좋아지는 것이 목표입니다.

## Tuning Loop

```text
choose query suite
  -> capture baseline evidence
  -> classify misses
  -> improve evidence
     metadata/contracts/aliases
  -> rerun the same suite
  -> compare metrics
     and evidence
  -> promote repeatable
     improvements
```

변경 전후에 같은 fixture, source artifact, Top-K 값을 사용합니다. 그렇지 않으면 의미 있는
비교가 아닙니다.

## Query Suite부터 시작하기

실제 업무를 대표하는 작은 suite를 만듭니다. 각 case에는 query, expected target, 검증할
stage가 있어야 합니다.

<Tabs>
  <TabItem value="search" label="Search" default>

```json
{
  "id": "refund_list",
  "query": "환불 가능한 주문을 찾아줘",
  "expected_target": "searchOrders",
  "mode": "search",
  "top_k": 8
}
```

  </TabItem>
  <TabItem value="plan" label="Plan">

```json
{
  "id": "order_detail",
  "query": "1001번 주문 상세를 조회해줘",
  "expected_target": "getOrderDetail",
  "mode": "plan",
  "provided_entities": {"orderId": "1001"}
}
```

  </TabItem>
  <TabItem value="execute" label="Execute">

```json
{
  "id": "readonly_detail",
  "query": "1001번 주문 상세를 조회해줘",
  "expected_target": "getOrderDetail",
  "mode": "execute",
  "mutation_safety": "read_only",
  "assertions": [{"path": "status", "exists": true}]
}
```

  </TabItem>
</Tabs>

개발 중에는 suite를 작게 유지합니다. release나 public quality claim 전에는 범위를 넓힙니다.

## Evidence 캡처

Search를 튜닝할 때는 `include_evidence=True`를 사용합니다. evidence object는 retrieval,
target selection, planning, product UI 사이의 debug 가능한 contract입니다.

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.load("collection.json")
baseline = retrieve_graphify(
    graph,
    query="환불 가능한 주문을 찾아줘",
    top_k=8,
    include_evidence=True,
)

for row in baseline["results"]:
    print(row["name"])
    print(row["score_breakdown"])
    print(row.get("semantic_evidence", {}))
```

캡처할 항목:

- ranked candidate name
- expected target rank
- score breakdown
- semantic/contract evidence
- graph expansion source
- token budget used
- case가 target selection을 포함한다면 selector decision

raw auth header, cookie, full request body, full response body, user identifier,
secret은 저장하지 않습니다.

## Signal 읽기

Evidence quality부터 봅니다. weight 변경은 마지막 단계입니다.

| Signal | 언제 확인하나 | 가능한 조치 |
| --- | --- | --- |
| `seed` | expected tool이 Top-K 밖 | name, summary, alias |
| `action_match` | search/read/create/update/delete intent가 틀림 | `canonical_action` derivation |
| `resource_match` | action은 맞지만 object가 틀림 | `primary_resource` 또는 resource alias |
| `module_match` | 대형 catalog에서 다른 domain이 올라옴 | `path_module`, operation group, module alias |
| `shape_match` | list/detail/count/mutation sibling이 틀림 | `result_shape` derivation |
| `contract_match` | query entity가 무시됨 | request/response contract extraction |
| `graph_expansion` | producer 또는 next-step tool이 빠짐 | data-flow edge와 producer expansion |
| `learning` | 반복 성공 correction이 재사용되지 않음 | shadow/promotion state |

signal이 비어 있다면 source evidence를 고칩니다. signal은 있는데 여러 case에서 약하다면
그때 weight tuning을 검토합니다.

## Miss Taxonomy

코드를 바꾸기 전에 실패 case를 먼저 분류합니다.

| Category | 의미 | 먼저 볼 곳 |
| --- | --- | --- |
| `not_retrieved` | expected target이 Top-K 밖 | indexed text와 semantic metadata |
| `low_rank` | expected target은 있지만 약한 sibling 아래에 있음 | score breakdown과 shape/resource evidence |
| `wrong_shape` | list/detail/count/mutation이 헷갈림 | `result_shape`, response schema, operation id |
| `wrong_resource` | action은 맞지만 business object가 틀림 | `primary_resource`, path module, alias |
| `module_leak` | 대형 catalog에서 다른 domain이 이김 | `path_module`, source label, module alias |
| `producer_missing` | target은 찾았지만 required field를 못 채움 | `api_contract.produces`와 data-flow edge |
| `selector_mismatch` | 정답 tool은 Top-K에 있지만 final target이 틀림 | `target_selector.rank_signals` |
| `auth_or_execute` | search/plan은 통과했지만 API call이 실패 | auth readiness, runner event, HTTP status |

category를 섞지 않습니다. search miss와 execution auth failure는 다른 수정이 필요합니다.

## Tuning Actions

Evidence를 개선하는 가장 작은 product-neutral fix부터 적용합니다.

| Action | Scope | Notes |
| --- | --- | --- |
| generic alias 추가 | adapter options | 사용자가 OpenAPI에 없는 업무 용어를 쓸 때 |
| semantic derivation 개선 | engine | 많은 operation이 같은 naming pattern을 공유할 때 |
| response schema repair | source 또는 adapter repair | producer expansion과 result shape에 필요 |
| request schema repair | source 또는 adapter repair | plan synthesis와 missing field diagnostics에 필요 |
| manual edge 추가 | artifact metadata | source가 표현하지 못하는 알려진 workflow relation |
| learning suggestion promote | collection-local | 반복 검증된 성공 후에만 사용 |
| ranking weight 조정 | engine policy | evidence가 있고 여러 case가 지지할 때만 사용 |

engine에 일회성 operation-name hack을 넣지 않습니다. 특정 고객, endpoint, private field name을
언급하는 rule은 adapter option 또는 manual metadata에 둡니다.

## Alias Strategy

Alias는 사용자와 OpenAPI 작성자가 서로 다른 단어를 쓸 때 유용합니다.

```python
artifact = build_openapi_collection_artifact(
    "openapi.json",
    semantic_options={
        "resource_aliases": {
            "refund": "claim",
            "buyer": "customer",
            "delivery": "shipment",
        },
        "action_aliases": {
            "lookup": "read",
            "find": "search",
        },
    },
)
```

alias는 generic하게 유지합니다. product adapter는 build 시 customer-specific alias를 넘길
수 있지만 library는 reusable해야 합니다.

## Selector Tuning

expected target이 이미 Top-K 안에 있다면 retrieval을 넓히기보다 target selection을
점검합니다.

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query=case["query"],
    candidates=[
        row["name"]
        for row in retrieval["results"]
    ],
    tools=artifact["tools"],
    retrieval_results=retrieval["results"],
    llm_target=llm_target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
print(selection["rank_signals"])
```

selector override는 strong evidence와 충분한 margin이 있을 때만 건강합니다. weak evidence는
조용히 고치지 말고 `ambiguous_target`으로 남겨야 합니다.

## Learning Evidence

Trace learning은 보수적으로 다룹니다.

1. scrubbed attempt를 저장합니다.
2. shadow mode에서 suggestion을 만듭니다.
3. baseline rank와 learning-applied shadow rank를 비교합니다.
4. 반복 성공한 target 또는 plan-path evidence만 promote합니다.
5. learning boost는 low-weight로 두고 `rank_signals`에 노출합니다.

성공 실행 한 번을 영구 ranking truth로 취급하지 않습니다.

## Acceptance Gates

Tuning 변경은 최소 다음을 보고해야 합니다.

| Metric | 필요한 이유 |
| --- | --- |
| query count | 예시 하나로 과장하지 않기 위해 |
| Top-1 hit rate | 직접 ranking quality |
| Top-3 또는 Top-8 hit rate | LLM/selector handoff용 recall |
| average candidate count | context pressure |
| max candidate count | worst-case prompt size |
| selector override count | guardrail activity |
| selector ambiguity count | unresolved sibling confusion |
| plan hit rate | search result가 planning에 실제로 유용한지 |
| `unsatisfied_field` count | contract quality |
| uncaught error count | adapter/runtime stability |

public claim에는 LLM이 결과에 포함된 경우 model/provider 정보를 함께 기록합니다.

## Anti-Patterns

피해야 할 것:

- engine에 product-specific operation name을 하드코딩
- noisy OpenAPI text가 결과를 지배하도록 raw description을 과하게 boost
- query 하나를 고치려고 global weight 변경
- manual demo query만 보고 개선 선언
- 정답이 보일 때까지 Top-K를 늘려 LLM context를 과도하게 키우기
- search evidence에 secret이나 raw API payload 저장
- 반복 검증 없이 learning suggestion promote

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Validation Benchmarks](../validation/benchmarks.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../learning/shadow-promotion.md)
