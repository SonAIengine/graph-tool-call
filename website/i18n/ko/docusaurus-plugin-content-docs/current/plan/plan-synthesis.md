---
title: Plan 합성
description: 선택된 target, entities, context defaults, contract evidence로 실행 가능한 tool path를 만듭니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Plan 합성

Plan synthesis는 선택된 target tool을 실행 가능한 path로 바꿉니다. 어떤 argument가 이미
알려져 있는지, 어떤 field를 collection context로 채울 수 있는지, 어떤 upstream producer
tool이 missing value를 공급할 수 있는지, 어떤 값을 사용자에게 물어야 하는지를 결정합니다.

Synthesizer는 deterministic하고 transport-agnostic합니다. graph와 tool metadata를
소비할 뿐 HTTP API를 호출하거나, product DB를 읽거나, runtime auth를 해결하거나, UI와
통신하지 않습니다. 그런 책임은 adapter에 남습니다.

Tool 선택은 맞았지만 이 tool을 안전하게 어떻게 호출할지 설명해야 할 때 이 페이지를 보면
됩니다.

## 어디에서 실행되나

Plan synthesis는 target selection 이후, execution 이전에 실행됩니다.

| Stage | Input | Output | Owner |
| --- | --- | --- | --- |
| Intent parsing | user query | target hint, entities | LLM 또는 adapter |
| Target selection | candidates and evidence | final selected target | graph-tool-call |
| Plan synthesis | target, entities, graph contracts | `Plan` 또는 structured error | graph-tool-call |
| User input | missing slots and enum mappings | resumed input context | product adapter |
| Execution | plan and runtime auth | runner events | product adapter + `PlanRunner` |

Plan synthesis가 실패하면 unknown target인지, required field가 미충족인지, enum mapping이
필요한지, dynamic option이 필요한지, cycle인지, depth limit인지 reason code로 설명해야
합니다.

## Public API

<Tabs>
  <TabItem value="basic" label="기본" default>

```python
from graph_tool_call.plan import PathSynthesizer

synthesizer = PathSynthesizer(
    graph_payload,
    context_defaults={"locale": "ko_KR"},
    enum_field_names={"statusCode"},
)

plan = synthesizer.synthesize(
    target="getOrderDetail",
    entities={"orderNo": "A-100"},
    goal="Find order detail",
)
```

  </TabItem>
  <TabItem value="with-selector" label="Selector와 함께">

```python
from graph_tool_call.graphify import select_target_candidate
from graph_tool_call.plan import PathSynthesizer

selection = select_target_candidate(
    query=query,
    candidates=retrieval_rows,
    tools=graph_payload["tools"],
    retrieval_results=retrieval_rows,
    llm_target=intent.target,
)

synthesizer = PathSynthesizer(
    graph_payload,
    context_defaults=collection_context_defaults,
    enum_field_names=collection_enum_field_names,
)

plan = synthesizer.synthesize(
    target=selection["selected_target"],
    entities=intent.entities,
    goal=query,
)
plan.metadata.setdefault("synthesis", {})["target_selector"] = selection
```

  </TabItem>
  <TabItem value="run-stream" label="Run stream">

```python
from dataclasses import asdict

from graph_tool_call.plan import PlanRunner

runner = PlanRunner(call_tool)

for event in runner.run_stream(
    plan,
    input_context={"orderNo": "A-100"},
    trace_metadata={"collection_id": "bo-dev"},
):
    forward_to_sse(asdict(event))
```

  </TabItem>
</Tabs>

## Input Contract

`PathSynthesizer`는 graph artifact와 optional collection setting으로 초기화합니다.

| Constructor Argument | Type | Purpose |
| --- | --- | --- |
| `graph` | `dict` | tools, metadata, edges가 포함된 graph artifact |
| `max_depth` | `int` | producer-chain 최대 depth. 기본값 `5` |
| `context_defaults` | `dict` | locale, tenant, site, channel 같은 ambient collection value |
| `enum_field_names` | `set[str]` | producer chaining 대신 adapter/user enum mapping을 써야 하는 field |

`synthesize()`는 selected target과 runtime entities를 받습니다.

| Method Argument | Type | Purpose |
| --- | --- | --- |
| `target` | `str` | 최종 selected tool name |
| `entities` | `dict` | user request에서 추출되었거나 adapter가 공급한 값 |
| `goal` | `str` | plan에 저장되는 사람이 읽을 수 있는 목표 |
| `exclude_tools` | `set[str]` | repair 또는 retry 중 피해야 할 producer tool |

가능하면 tool에는 `metadata.api_contract.consumes`와
`metadata.api_contract.produces`가 있어야 합니다. metadata가 약해도 동작은 가능하지만,
plan 설명력이 낮아지고 사용자 입력이 더 자주 필요해집니다.

## Input Priority

필수 consume field마다 synthesizer는 안정적인 순서로 값을 찾습니다.

| Priority | Source | Example |
| --- | --- | --- |
| 1 | user 또는 LLM-extracted `entities` | `{"orderNo": "A-100"}` |
| 2 | context field용 `context_defaults` | `siteNo`, `locale`, `channel` |
| 3 | semantic tag가 같은 producer tool | search step이 produce한 `member_id` |
| 4 | field name이 같은 producer tool | `ordNo` -> `ordNo` |
| 5 | graph edge 또는 workflow fallback | curated producer relation |
| 6 | 허용된 경우 user input fallback | `${user_input.statusCode}` |

이 순서는 사용자가 명시한 사실을 graph inference보다 우선하고, collection context를
라이브러리 내부 하드코딩 없이 유지합니다.

## Plan Shape

합성된 plan은 `Plan`과 `PlanStep`으로 구성된 serializable artifact입니다.

```python
from graph_tool_call.plan import Plan, PlanStep

plan = Plan(
    id="plan-001",
    goal="Find order detail",
    steps=[
        PlanStep(
            id="s1",
            tool="searchOrders",
            args={"keyword": "A-100"},
        ),
        PlanStep(
            id="s2",
            tool="getOrderDetail",
            args={"orderNo": "${s1.items.0.orderNo}"},
            depends_on=["s1"],
        ),
    ],
    output_binding="${s2}",
    metadata={
        "target": "getOrderDetail",
        "synthesis": {
            "target": "getOrderDetail"
        }
    },
)
```

`PlanStep.args`에는 binding expression이 들어갈 수 있습니다.

| Binding | 의미 |
| --- | --- |
| `${input.orderNo}` | `input_context`에서 온 값 |
| `${user_input.statusCode}` | user slot으로 수집된 값 |
| `${s1.items.0.orderNo}` | 이전 step output에서 온 값 |
| `${s2}` | step `s2`의 전체 output |

`PlanRunner`가 execution time에 binding을 resolve합니다. Synthesizer는 dependency를
선언할 뿐입니다.

## 보존할 Metadata

Adapter는 `Plan.metadata.synthesis`를 저장하는 것이 좋습니다. 이 값이 plan construction의
핵심 debugging contract입니다.

| Field | 목적 |
| --- | --- |
| `target` | 최종 selected target |
| `selected_producers` | required field를 채우는 데 사용된 producer tool |
| `candidate_signals` | producer candidate가 rank된 이유 |
| `fallbacks` | user input으로 fallback된 field |
| `user_input_slots` | UI가 바로 쓸 수 있는 missing input list |
| `context_defaults` | 사용된 context key. secret value는 저장하지 않음 |
| `enum_field_names` | enum mapping이 필요한 field |
| `target_selector` | LLM target, final target, override diagnostics |

Product log에는 field name, kind, semantic tag, reason code를 저장하세요. raw auth header,
cookie, user identifier는 저장하지 않습니다.

## User Input Slots

required value를 자동으로 채울 수 없지만 user input이 허용되면 plan은
`user_input_slots`를 기록합니다.

```json
{
  "step_id": "s2",
  "tool": "getOrderDetail",
  "field_name": "statusCode",
  "required": true,
  "kind": "data",
  "location": "query",
  "semantic_tag": "order_status",
  "reason": "enum_required"
}
```

Adapter는 하나의 popup으로 값을 수집한 뒤 같은 plan을 resume할 수 있습니다.

```python
for event in runner.run_stream(
    plan,
    input_context={"statusCode": "COMPLETE"},
):
    handle(event)
```

라이브러리는 UI 동작을 강제하지 않습니다. 안정적인 slot metadata만 제공합니다.

## Failure Reasons

`PlanSynthesisError`는 `to_dict()`를 제공합니다. Adapter는 exception message를 parsing할
필요 없이 structured diagnostic을 저장할 수 있습니다.

```python
from graph_tool_call.plan import PlanSynthesisError

try:
    plan = synthesizer.synthesize(target="getOrderDetail", entities={})
except PlanSynthesisError as exc:
    result = exc.to_dict()
    print(result["reason"])
```

대표 reason code:

| Reason | 의미 | Adapter Response |
| --- | --- | --- |
| `unknown_target` | target tool이 graph에 없음 | retrieval rerun 또는 selector 확인 |
| `unsatisfied_field` | required field를 채울 수 없음 | user에게 묻기, context default 추가, producer contract 개선 |
| `enum_required` | required enum에 user 또는 adapter mapping 필요 | enum mapping UI 표시 |
| `dynamic_option_required` | dynamic option list를 먼저 가져와야 함 | option producer 호출 후 user 선택 |
| `cycle` | producer search가 이미 처리 중인 tool을 다시 방문 | graph edge 확인 |
| `max_depth` | producer chain이 configured depth 초과 | graph noise 축소 또는 depth 신중히 증가 |
| `user_input_fallback` | user input 이후에만 plan 진행 가능 | user slot 렌더링 후 resume |

Structured failure reason은 public contract입니다. Quality Lab, SSE/log event, operator
diagnostic에 그대로 사용하세요.

## Dynamic Option Flow

일부 field는 text에서 추측하면 안 되고 긴 producer chain으로 채우면 안 됩니다. enum-like
code, product option, UI selection value가 대표적입니다.

single-hop producer가 유용한 option list를 가져올 수 있으면 synthesis는 dynamic option
diagnostic을 줄 수 있습니다.

| Field | 의미 |
| --- | --- |
| `field_name` | 값이 필요한 field |
| `semantic_tag` | field의 semantic category |
| `producer_name` | option을 가져올 수 있는 tool |
| `options_path` | response에서 option list가 있는 path |
| `label_field_hints` | UI label 후보 field |

Adapter는 producer를 호출하고, 선택지를 보여준 뒤, 선택된 값으로 plan execution을
resume합니다.

## Runner Handoff

Plan synthesis는 plan을 생성합니다. `PlanRunner`는 adapter callback을 통해 실행합니다.

```python
def call_tool(tool_name: str, args: dict) -> dict:
    # Adapter responsibility:
    # - resolve base URL
    # - attach auth/session headers
    # - execute HTTP/MCP/function call
    # - normalize response shape
    return execute_collection_tool(tool_name, args)

runner = PlanRunner(call_tool, validate_args="coerce")

events = list(
    runner.run_stream(
        plan,
        input_context=entities,
        trace_metadata={
            "collection_id": collection_id,
            "graph_tool_call_version": graph_tool_call.__version__,
        },
    )
)
```

Runner event에는 `plan_id`, `step_id`, `tool`, stage, error kind, duration,
trace metadata가 보존되어야 합니다. event schema는 [Runner Events](./runner-events.md)를
참고하세요.

## Adapter Boundary

graph-tool-call은 deterministic plan construction을 담당합니다. Runtime system은 product
adapter가 담당합니다.

| Responsibility | Owner |
| --- | --- |
| field dependency analysis | graph-tool-call |
| producer search | graph-tool-call |
| plan artifact and synthesis metadata | graph-tool-call |
| auth profile lookup | adapter |
| session/header resolution | adapter |
| HTTP execution | adapter |
| user popup and resume UX | adapter |
| persistence and audit retention | adapter |

Product-specific DB, auth, cookie, user ID, SSE UI 코드는 라이브러리에 넣지 마세요.
엔진에는 product-neutral graph metadata만 전달합니다.

## Quality Checks

Plan synthesis 품질은 execution과 분리해서 테스트해야 합니다. downstream API 401은 plan
synthesis 실패로 세면 안 됩니다.

| Check | Expected Result |
| --- | --- |
| known target | plan final step equals selected target |
| entity fill | explicit entity value가 producer보다 우선 |
| context default | context field가 user prompt 없이 채워짐 |
| producer path | missing data field가 upstream producer step 생성 |
| enum field | enum mapping이 user slot 또는 structured error 생성 |
| cycle guard | cyclic graph가 `cycle`로 실패 |
| max depth | 긴 chain이 `max_depth`로 실패 |
| metadata | `Plan.metadata.synthesis`에 target, producers, slots 포함 |

유용한 명령:

```bash
poetry run pytest tests/test_plan_synthesizer.py -q
poetry run pytest tests/test_runner.py -q
poetry run pytest tests/test_graphify_contract_025.py -q
```

Product validation에서는 Quality Lab plan case를 실행하고 아래를 비교합니다.

- selected target
- plan tools
- user input slots
- failure reason
- synthesis latency
- auth readiness 이후의 execution status

## Troubleshooting

| Symptom | Likely Cause | What To Inspect |
| --- | --- | --- |
| `unknown_target` | selector가 graph에 없는 이름을 선택 | target selector output and graph artifact |
| required field missing | entity extraction 또는 contract coverage 약함 | `api_contract.consumes`, `user_input_slots` |
| producer step이 너무 많음 | graph structural edge가 너무 넓음 | edge quality and producer candidate signals |
| enum value가 잘못 추측됨 | enum field가 ordinary data로 처리됨 | `enum_field_names`, user input slots |
| runner binding failure | response shape가 contract와 다름 | producer output, response envelope, binding path |
| plan은 통과하지만 API 실패 | auth 또는 downstream request 문제 | runner events and auth readiness |

## 운영 가이드

Production-ready collection은 아래 상태여야 합니다.

- synthesis 이전 target selection이 안정적임
- 중요한 operation의 request/response contract coverage가 충분함
- ambient runtime field용 context default가 있음
- operator choice가 필요한 field의 enum mapping이 있음
- high-frequency workflow용 Quality Lab plan fixture가 있음
- runner trace에 stage와 failure reason이 보존됨
- plan metadata와 trace record에 raw secret이 없음

대형 API collection을 개선할 때는 아래 순서로 디버깅하세요.

1. expected tool이 retrieval Top-K에 있는지 확인
2. target selector evidence 확인
3. explicit entities로 plan synthesis 실행
4. missing fields와 producer candidates 확인
5. context defaults 또는 enum mappings 추가
6. auth readiness가 통과한 뒤 execution 실행

## 관련 문서

- [Target Selection](../search/target-selection.md)
- [User Input Slots](./user-input-slots.md)
- [Runner Events](./runner-events.md)
- [Failure Taxonomy](./failure-taxonomy.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
