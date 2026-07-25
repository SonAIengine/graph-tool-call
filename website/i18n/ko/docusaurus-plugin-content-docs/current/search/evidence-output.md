---
title: Evidence 출력
description: tool이 왜 검색, 확장, 선택됐는지 확인합니다.
---

# Evidence 출력

Evidence output은 debuggable retrieval engine과 black-box prompt를 나누는 핵심입니다.

아래 질문에 답해야 하는 product에서 사용합니다.

- 왜 이 tool이 검색됐는가
- 왜 producer tool이 확장됐는가
- selector가 왜 LLM target을 수용하거나 override했는가
- 실패가 search, selection, planning, auth, execution 중 어디에서 왔는가

## Minimal Example

```python
from graph_tool_call.graphify import retrieve_graphify

response = retrieve_graphify(
    graph,
    query="환불 가능한 주문을 찾아줘",
    top_k=8,
    include_evidence=True,
)

first = response["results"][0]
print(first["tool_name"])
print(first["score_breakdown"])
print(first["candidate_evidence"])
```

`include_evidence=True`는 product diagnostic, regression case, Quality Lab 스타일
검증을 위한 옵션입니다. 작은 local demo에는 필요하지 않을 수 있습니다.

## Result Fields

| Field | 의미 |
| --- | --- |
| `tool_name` | candidate tool name |
| `score` | 최종 retrieval score |
| `score_breakdown` | ranking에 사용된 named additive signal |
| `seeds` | graph traversal 전 initial keyword/semantic match |
| `expanded_from` | 이 tool을 추가하게 만든 candidate |
| `edge_evidence` | expansion 중 사용된 graph edge evidence |
| `candidate_evidence` | selector가 사용할 action/resource/shape/contract evidence |
| `token_budget_used` | rendered subgraph의 대략적인 context budget |

field set은 additive입니다. Product code는 unknown field를 보존해야 새 engine version이
더 많은 evidence를 노출해도 adapter가 깨지지 않습니다.

## Product UI에 보여줄 것

candidate별로 아래를 보여주는 것이 좋습니다.

- rank
- score
- score breakdown
- matched action/resource/module
- matched contract field
- graph expansion source
- selector reason code

selected target에는 추가로 아래를 보여줍니다.

- LLM target
- final selected target
- selector가 LLM을 override했는지
- ambiguous flag
- selector policy
- reason code

## 저장 정책

decision을 재현하는 데 필요한 compact, scrubbed evidence만 저장합니다. raw request
body, response body, token, cookie, user identifier는 저장하지 않습니다.

저장할 값:

- query fingerprint 또는 test case id
- candidate list와 rank
- score breakdown
- selector reason code
- graph/tool version
- scrub된 trace metadata

저장하지 않을 값:

- full API response body
- authorization header
- cookie
- raw user id
- request/response payload 내부 개인정보

## Failure Modes

| 증상 | 가능한 원인 | 확인할 것 |
| --- | --- | --- |
| score는 높은데 target이 틀림 | noisy text 또는 sibling tie | `score_breakdown`, `candidate_evidence.shape_match` |
| 정답 target이 없음 | metadata 또는 alias 부족 | indexed action/resource/module field |
| producer가 없음 | contract extraction gap | `api_contract.consumes`, `api_contract.produces` |
| selector가 override하지 않음 | margin 부족 | `target_selector.rank_signals` |
| evidence가 비어 있음 | `ToolGraph.retrieve()` 경로를 사용함 | `retrieve_graphify(..., include_evidence=True)` 사용 |

## Validation

Ranking을 튜닝할 때 evidence output을 regression fixture에 저장합니다. 실패 query는
이전 run과 새 run의 evidence를 같이 남겨야 감이 아니라 diff로 리뷰할 수 있습니다.

유용한 체크:

```bash
poetry run pytest tests/test_graphify_contract_025.py -q
poetry run pytest tests/test_graphify_collection_artifact.py -q
```

## 관련 문서

- [Tool Graph Search](./tool-graph-search.mdx)
- [Target Selection](./target-selection.md)
- [Trace Learning](../concepts/trace-learning.md)
