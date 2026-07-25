---
title: Evidence 출력
description: tool이 왜 검색, 확장, 선택, 거절됐는지 확인합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Evidence 출력

Evidence output은 debuggable retrieval engine과 black-box prompt를 나누는 핵심입니다.
tool이 왜 보였고, ranking 되었고, 확장되었고, 선택 또는 거절되었는지를 compact signal로
남깁니다.

아래 질문에 답해야 하는 product에서 사용합니다.

- 왜 이 tool이 검색됐는가
- 왜 producer 또는 neighbor tool이 확장됐는가
- selector가 왜 LLM target을 수용, 거절, override했는가
- 실패가 search, selection, planning, auth, execution 중 어디에서 왔는가
- benchmark 또는 Quality Lab run 사이에 어떤 artifact가 바뀌었는가

## Minimal Example

<Tabs>
  <TabItem value="graphify" label="Graphify" default>

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph_json,
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
  <TabItem value="selector" label="Selector">

```python
from graph_tool_call.graphify import select_target_candidate

selection = select_target_candidate(
    query="환불 가능한 주문을 찾아줘",
    candidates=[row["tool_name"] for row in response["results"]],
    tools=tools_by_name,
    retrieval_results=response["results"],
    llm_target=llm_target,
)

print(selection["selected_target"])
print(selection["reason_codes"])
```

  </TabItem>
  <TabItem value="fixture" label="Fixture">

```json
{
  "case_id": "refund-order-search-001",
  "query": "환불 가능한 주문을 찾아줘",
  "expected_target": "getRefundableOrderList",
  "top_k": 8,
  "capture_evidence": true
}
```

  </TabItem>
</Tabs>

`include_evidence=True`는 product diagnostic, regression case, Quality Lab 스타일
검증을 위한 옵션입니다. 작은 local demo는 더 단순한 retrieval API를 사용해도 됩니다.

## Response Shape

top-level response는 additive object로 다룹니다. adapter는 unknown key를 보존해야 새
engine version이 evidence를 추가해도 기존 product code가 깨지지 않습니다.

| Field | 의미 |
| --- | --- |
| `query` | caller path에 따라 normalized 또는 original query |
| `results` | ranked candidate row |
| `seeds` | expansion 전 initial keyword 또는 semantic match |
| `token_budget_used` | 대략적인 retrieval context size |
| `graph_tool_call_version` | evidence를 만든 engine version |
| `trace_metadata` | optional caller-provided execution/debug context |

## Candidate Row

| Field | 의미 |
| --- | --- |
| `tool_name` | candidate tool name |
| `rank` | 반환 list에서 candidate 위치 |
| `score` | 최종 retrieval score |
| `score_breakdown` | ranking에 사용된 named additive signal |
| `seeds` | graph traversal 전에 candidate를 보이게 만든 match |
| `expanded_from` | 이 tool을 추가하게 만든 candidate |
| `edge_evidence` | expansion 중 사용된 graph edge evidence |
| `candidate_evidence` | selector가 사용할 action/resource/shape/contract evidence |
| `token_budget_used` | 이 rendered candidate context의 대략적인 budget |

안정 contract는 고정된 절대 score scale이 아니라 이름 붙은 evidence field가 존재한다는
점입니다.

## Example Result

```json
{
  "tool_name": "getRefundableOrderList",
  "rank": 1,
  "score": 0.83,
  "score_breakdown": {
    "keyword_match": 0.31,
    "action_match": 0.16,
    "resource_match": 0.18,
    "shape_match": 0.08,
    "contract_match": 0.07,
    "graph_expansion": 0.03,
    "learning": 0.0
  },
  "candidate_evidence": {
    "semantic_match": ["search", "order", "list"],
    "contract_match": ["orderStatus", "refundStatus"],
    "result_shape": "list"
  },
  "edge_evidence": []
}
```

이 값은 ranked explanation으로 읽어야 합니다. future version에서도 같은 numeric weight를
쓴다는 약속은 아닙니다.

## Diagnostic Workflow

evidence object는 아래 순서로 읽습니다.

1. expected target이 `results`에 있는지 확인합니다.
2. rank가 caller의 Top-K 기준에 맞는지 확인합니다.
3. 잘못된 상위 tool과 `score_breakdown`을 비교합니다.
4. `candidate_evidence`에서 action, resource, shape, contract field 누락을 봅니다.
5. producer tool이 생기거나 사라졌다면 `expanded_from`과 `edge_evidence`를 봅니다.
6. LLM 탓으로 넘기기 전에 같은 result row를 `select_target_candidate()`에 넘겨봅니다.

## Product UI Contract

candidate별로 raw metadata dump가 아니라 compact evidence를 보여줍니다.

| UI Field | Source |
| --- | --- |
| rank와 tool name | `rank`, `tool_name` |
| score chip | `score_breakdown` |
| action/resource/shape badge | `candidate_evidence.semantic_match` |
| matched field | `candidate_evidence.contract_match` |
| Top-K에 들어온 이유 | `seeds`, `expanded_from` |
| graph reason | `edge_evidence.kind`, `edge_evidence.evidence` |

selected target에는 아래를 추가합니다.

| UI Field | Source |
| --- | --- |
| LLM target | `target_selector.llm_target` |
| final selected target | `target_selector.selected_target` |
| override state | `target_selector.overrode_llm` |
| uncertainty | `target_selector.ambiguous`, `reason_codes` |
| policy | `target_selector.policy` |

이 정도면 operator가 search failure, selector ambiguity, missing input, auth readiness,
downstream API failure를 구분할 수 있습니다.

## 저장 정책

decision을 재현하는 데 필요한 compact, scrubbed evidence만 저장합니다. raw request body,
response body, token, cookie, user identifier는 저장하지 않습니다.

저장할 값:

- query fingerprint 또는 test case id
- candidate list와 rank
- score breakdown
- selector reason code
- graph/tool version
- scrubbed trace metadata
- 적용된 learning suggestion id

저장하지 않을 값:

- full API response body
- authorization header
- cookie
- raw user id
- phone, email, address, account-like payload value
- secret을 포함할 수 있는 raw prompt trace

## Failure Modes

| 증상 | 가능한 원인 | 확인할 것 |
| --- | --- | --- |
| score는 높은데 target이 틀림 | noisy text 또는 sibling tie | `score_breakdown`, `candidate_evidence.shape_match` |
| 정답 target이 없음 | metadata 또는 alias 부족 | indexed action/resource/module field |
| producer가 없음 | contract extraction gap | `api_contract.consumes`, `api_contract.produces` |
| producer가 너무 많음 | broad data-flow edge 또는 context field 폭발 | `edge_evidence`, contract field kind |
| selector가 override하지 않음 | margin 부족 | `target_selector.rank_signals` |
| evidence가 비어 있음 | simple retrieval path 사용 | `retrieve_graphify(..., include_evidence=True)` 사용 |
| rebuild 뒤 evidence가 바뀜 | artifact 또는 semantic metadata 변경 | `graph_tool_call_version`, `semantic_summary` 비교 |

## Regression Fixture

실패 run과 수정 run의 evidence를 같이 저장하면 감이 아니라 artifact diff로 review할 수
있습니다.

```json
{
  "case_id": "member-delivery-detail-001",
  "query": "회원 배송지 상세 정보를 보여줘",
  "expected_target": "getMemberDeliveryDetail",
  "actual_top_3": [
    {
      "tool_name": "getMemberDeliveryDetail",
      "rank": 1,
      "score_breakdown": {
        "resource_match": 0.18,
        "shape_match": 0.08,
        "contract_match": 0.07
      }
    }
  ],
  "target_selector": {
    "selected_target": "getMemberDeliveryDetail",
    "reason_codes": ["selected_by_strong_evidence"]
  }
}
```

## 검증

Ranking을 튜닝할 때 evidence output을 regression fixture에 저장합니다. 실패 query는 이전
run과 새 run의 evidence를 같이 남깁니다.

유용한 체크:

```bash
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Retrieval Signals](./retrieval-signals.md)
- [Target Selection](./target-selection.md)
- [Trace Learning](../concepts/trace-learning.md)
