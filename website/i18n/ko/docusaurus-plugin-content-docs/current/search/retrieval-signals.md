---
title: Retrieval 신호
description: graph-tool-call 검색 결과에 영향을 주는 ranking evidence를 설명합니다.
---

# Retrieval 신호

Retrieval은 설명 가능해야 합니다. candidate는 prompt가 우연히 선호해서가 아니라,
이름 붙은 signal 때문에 이겨야 합니다.

signal은 두 곳에서 사용됩니다.

- LLM이 tool을 보기 전에 compact candidate set을 ranking
- target selector가 candidate를 신뢰하거나 거절한 이유 설명

## Core Signals

| Signal | Source | 중요한 이유 |
| --- | --- | --- |
| `keyword_match` | tool name, operation id, summary, description | 직접적인 textual intent를 잡음 |
| `action_match` | `metadata.ai_metadata.canonical_action` | search/read/create/update/delete intent 분리 |
| `resource_match` | `metadata.ai_metadata.primary_resource` | business object를 맞춤 |
| `module_match` | `metadata.openapi.path_module` 또는 operation group | 대형 enterprise API 범위를 좁힘 |
| `shape_match` | `metadata.ai_metadata.result_shape` | list/detail/count/mutation sibling 구분 |
| `contract_match` | request/response contract field | 사용자 entity와 field evidence가 맞는지 확인 |
| `graph_expansion` | producer, consumer, manual, trace, curated edge | workflow 주변 tool을 후보에 포함 |
| `learning` | promoted trace-learning suggestion | 검증된 local feedback을 low-weight boost로 반영 |

## Evidence Output

signal detail은 `include_evidence=True`로 확인합니다.

```python
from graph_tool_call.graphify import retrieve_graphify

results = retrieve_graphify(
    graph,
    "find refund-ready orders",
    top_k=5,
    include_evidence=True,
)

for row in results:
    print(row["tool_name"], row["score_breakdown"])
```

일반적인 output은 다음과 같습니다.

```json
{
  "tool_name": "getRefundableOrderList",
  "score_breakdown": {
    "base_retrieval": 0.42,
    "learning": 0.02,
    "action_match": 1.0,
    "resource_match": 1.0,
    "module_match": 0.0,
    "shape_match": 1.0,
    "contract_match": 1.0,
    "graph_expansion": 0.1
  },
  "candidate_evidence": {
    "semantic_match": ["action", "resource", "shape"],
    "contract_match": ["orderNo", "claimStatus"]
  }
}
```

숫자의 절대 scale은 engine version에 따라 바뀔 수 있습니다. 안정 contract는 고정된 절대
score가 아니라 이름 붙은 signal과 evidence field가 남는 것입니다.

## Signal Interaction

| 상황 | 유용한 signal |
| --- | --- |
| 한국어 query, 영어 operation id | keyword, alias, Korean tokenizer, semantic metadata |
| list/detail sibling conflict | `shape_match`, response schema, operation id hint |
| 직접 검색되지 않은 tool | `graph_expansion`, producer/consumer edge |
| LLM이 틀린 target 선택 | selector `rank_signals`와 retrieval evidence |
| 반복 성공한 correction | promoted `learning` suggestion |

## Tuning 원칙

weight를 바꾸기 전에 metadata와 contract를 먼저 개선합니다.

1. expected tool이 Top-K에 있는지 확인합니다.
2. `score_breakdown`과 `candidate_evidence`를 봅니다.
3. text가 약하면 summary 또는 alias를 개선합니다.
4. list/detail이 헷갈리면 `result_shape`를 개선합니다.
5. upstream value가 필요하면 contract producer를 확인합니다.
6. evidence가 올바른 뒤에만 weight를 조정합니다.

## Best Practice

product debug screen과 regression fixture에는 `include_evidence=True`를
사용합니다. ranking을 설명하는 compact evidence만 저장하고 raw secret이나 full API
payload는 저장하지 않습니다.

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

## 검증

scoring 또는 metadata extraction을 바꾸면 retrieval-focused test를 실행합니다.

```bash
poetry run pytest tests/test_graphify_metadata.py tests/test_graphify_contract_025.py -q
```

## 관련 문서

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
- [Search Tuning](./search-tuning.md)
