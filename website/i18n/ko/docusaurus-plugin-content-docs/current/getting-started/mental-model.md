---
title: Mental Model
description: LLM이 실행하기 전에 graph-tool-call이 작고 근거 있는 tool surface를 만드는 방식을 설명합니다.
---

# Mental Model

`graph-tool-call`은 대형 tool catalog를 위한 retrieval과 planning 엔진입니다.

LLM을 대체하지 않습니다. LLM이 판단하기 전에 더 작고, 더 잘 정렬되고, 근거가 보이는
tool 후보군을 준비합니다.

## Core Problem

대형 tool catalog는 예측 가능한 이유로 실패합니다.

- LLM이 너무 많은 tool을 느슨한 설명과 함께 받음
- 비슷한 operation의 action/resource metadata가 약함
- request/response schema가 실행 가능한 contract로 변환되지 않음
- 정답 tool은 Top-K에 있지만 final target selection이 흔들림
- 실행을 시작한 뒤에야 missing field가 발견됨
- auth, request, API, cleanup failure가 섞임
- 성공한 retry가 future search로 되돌아가지 않음

graph-tool-call은 LLM이 행동하기 전에 catalog를 inspect 가능한 evidence로 바꿉니다.

## Pipeline

```text
source
  -> ingest
  -> contract extraction
  -> semantic build
  -> graph build
  -> retrieval
  -> target selection
  -> plan synthesis
  -> runner events
  -> trace learning
```

각 stage는 저장, 점검, 테스트, product adapter 전달이 가능한 artifact를 만듭니다.

## Stage Overview

| Stage | 하는 일 | Main Artifact |
| --- | --- | --- |
| ingest | OpenAPI, MCP, Python source를 tool로 변환 | `ToolSchema` |
| contract extraction | request/response/auth/context field 추출 | `metadata.api_contract` |
| semantic build | action, resource, module, result shape 추론 | `metadata.ai_metadata` |
| graph build | structural, contract, manual, trace edge merge | graph artifact |
| retrieval | query에 맞는 compact candidate set 정렬 | retrieval results |
| target selection | LLM target을 deterministic evidence로 guard | `target_selector` |
| plan synthesis | producer, binding, user input slot 순서화 | `Plan` |
| run | adapter가 tool을 실행하고 structured event stream | runner events |
| learn | scrub된 trace를 검증 후 suggestion으로 변환 | learning state |

## Artifact Flow

| Artifact | 존재 이유 | 보통 저장되는 위치 |
| --- | --- | --- |
| `ToolSchema` | 안정적인 tool description과 parameter | engine memory 또는 adapter storage |
| `metadata.openapi` | 원본 OpenAPI operation evidence | collection artifact |
| `metadata.api_contract` | consumes, produces, links, auth fields | collection artifact |
| `metadata.ai_metadata` | action/resource/module/search summary | collection artifact |
| `readiness_report` | build-time issue code와 readiness score | collection artifact와 UI |
| retrieval evidence | score breakdown과 matched signal | request trace 또는 Quality Lab |
| `target_selector` | final target decision과 override reason | plan metadata |
| `Plan` | 실행 가능한 ordered steps와 bindings | request runtime |
| runner events | stream 가능한 execution state와 failure | SSE/log/Quality Lab |
| learning suggestions | 반복 실행 trace에서 나온 safe feedback | collection-scoped learning block |

중요한 decision은 사람, test, adapter가 모두 읽을 수 있어야 합니다. 중요한 근거가 prompt
안에만 있으면 디버깅이 어렵습니다.

## Engine vs Adapter

graph-tool-call은 product-neutral logic을 맡습니다.

| Engine Owns | Adapter Owns |
| --- | --- |
| schema normalization | database rows |
| semantic metadata | user sessions |
| IO contracts | auth profiles |
| graph edges | HTTP execution |
| retrieval evidence | cookies and runtime headers |
| target selection | SSE transport |
| plan synthesis diagnostics | UI workflows |
| learning suggestions | collection persistence and promotion policy |

이 경계 덕분에 라이브러리를 재사용할 수 있습니다. XGEN은 auth profile을 전달하고 collection
artifact를 저장할 수 있지만, XGEN-specific DB, cookie, UI logic을 엔진에 넣지 않습니다.

## 왜 Graph인가

Tool 목록은 관계를 숨깁니다. Graph는 관계를 명시합니다.

- tool A가 field를 만들고 tool B가 그 field를 소비함
- 여러 operation이 같은 primary resource를 다룸
- search operation이 detail operation에 필요한 identifier를 만듦
- manual curated edge가 약한 name-based edge보다 강함
- 반복 성공 run이 trace evidence가 될 수 있음

이 관계는 planning에서 중요합니다. Catalog가 단순 description이 아니라 field와 edge
evidence를 갖기 때문에 engine은 producer step을 합성할 수 있습니다.

## LLM의 역할

LLM은 여전히 중요합니다. LLM은 아래 일을 할 수 있습니다.

- natural-language intent 해석
- compact하고 정렬된 candidate set 안에서 선택
- 자연어 gap 보완
- 사용자-facing final response 작성
- engine이 제공한 evidence를 바탕으로 reasoning

엔진은 LLM이 불필요한 catalog noise를 보지 않게 합니다. 첫 번째 최적화 대상은 model
fine-tuning이 아니라 더 좋은 evidence입니다.

## Search To Plan Example

```python
from graph_tool_call import ToolGraph
from graph_tool_call.plan import PathSynthesizer

graph = ToolGraph.from_url(openapi_url)

results = graph.retrieve_with_scores(
    "환불 가능한 주문을 보여줘",
    top_k=8,
)

target = results[0].name
plan = PathSynthesizer(graph.to_dict()).synthesize(
    target_tool=target,
    user_query="환불 가능한 주문을 보여줘",
    entities={"siteNo": "1001"},
)
```

Retrieval result는 tool이 왜 rank되었는지 설명합니다. Plan은 어떤 field가 이미
충족됐는지, 어떤 producer가 필요한지, 어떤 값이 user input 또는 context default에서
와야 하는지 설명합니다.

## Failure Handling

Run이 실패하면 prompt를 고치기 전에 stage를 분류합니다.

| 증상 | Likely Stage | 먼저 읽을 문서 |
| --- | --- | --- |
| expected tool이 Top-K에 없음 | retrieval | [Retrieval Signals](../search/retrieval-signals.md) |
| expected tool은 Top-K에 있는데 final target이 틀림 | target selection | [Target Selection](../search/target-selection.md) |
| obvious field인데 plan이 물어봄 | plan synthesis | [User Input Slots](../plan/user-input-slots.md) |
| API 호출 전 execute가 멈춤 | auth preflight | [Auth Readiness](../build/auth-readiness.md) |
| API가 400, 401, 500 반환 | execute | [Failure Taxonomy](../plan/failure-taxonomy.md) |
| retry는 성공했는데 future search가 안 좋아짐 | learning | [Trace Learning Loop](../concepts/trace-learning.md) |

## Quality Loop

품질은 loop로 측정해야 합니다.

1. catalog를 build합니다.
2. readiness와 graph evidence를 점검합니다.
3. search case를 실행합니다.
4. target-selection case를 실행합니다.
5. auth가 있으면 plan/execute case를 실행합니다.
6. scrub된 trace를 저장합니다.
7. learning을 shadow mode로 비교합니다.
8. 검증된 suggestion만 promote합니다.

이렇게 해야 단일 demo가 아니라 반복 가능한 evidence를 갖게 됩니다.

## Next Steps

- 최소 retrieval flow가 필요하면 [Quickstart](./quickstart.md)부터 보세요.
- Catalog를 만들 때는 [OpenAPI Ingestion](../build/openapi-ingestion.md)을 보세요.
- LLM target 선택이 흔들리면 [Target Selection](../search/target-selection.md)을 보세요.
- Tool chaining이 필요하면 [Plan Synthesis](../plan/plan-synthesis.md)을 보세요.
- 품질 claim 전에는 [Quality Lab](../validation/quality-lab.md)을 보세요.
