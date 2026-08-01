---
title: 후보 확장
description: evidence가 있는 경우 retrieved target에 producer tool과 graph neighbor를 확장합니다.
---

# 후보 확장

Candidate expansion은 initial search 이후 관련 tool을 추가합니다. 가장 중요한
확장은 producer discovery입니다. target이 required field를 소비한다면, graph는
그 field를 생산하는 tool을 포함할 수 있습니다.

이렇게 하면 LLM catalog는 작게 유지하면서도 plan synthesis가 required input을 채울
tool을 볼 수 있습니다.

## Minimal Example

```python
from graph_tool_call.graphify import expand_candidates_with_producers

expanded = expand_candidates_with_producers(
    candidate_names=["cancelOrder"],
    tools_by_name=tools_by_name,
    max_producers_per_field=2,
    max_hops=1,
)
```

`cancelOrder`가 `orderNo`를 요구하고 다른 tool이 `orderNo`를 produce한다면, target
selection 또는 planning 전에 producer가 candidate list에 추가될 수 있습니다.

## Target-Specific Dependency Closure

```python
from graph_tool_call.graphify import assemble_tool_bundle, complete_target_dependencies

closure = complete_target_dependencies(
    selected_target,
    tools_by_name,
    graph=tool_graph,
    available_fields={"tenant_id"},
    max_hops=3,
)
```

Closure는 target, required dependency, optional dependency를 별도 역할로 유지합니다.
OpenAPI graph에서 consumer-aligned output promotion은 producer coverage를 높일 수 있지만,
일치하는 모든 neighbor를 실행해도 된다는 뜻은 아닙니다. API contract edge는 required
field별로 해석하고, 출처 없는 structural `requires` edge는 optional hint로 남깁니다.

```bash
make paper-openapi-closure
```

이 gate는 required-producer recall, 전체 dependency 완성률, 불필요한 dependency,
표본 충분성을 함께 검사합니다. OpenAPI에서 optional인 workflow step은 query, manual,
OpenAPI Link 또는 promoted trace 근거가 생기기 전까지 planner의 판단으로 남깁니다.

## Expansion Sources

- deterministic IO contract edge
- OpenAPI link
- manual edge
- promoted run-observed trace edge
- high-confidence semantic link

## Inputs

| Parameter | 목적 |
| --- | --- |
| `candidate_names` | initial retrieved target |
| `tools_by_name` | 이름으로 indexing된 tool metadata |
| `max_producers_per_field` | missing required field마다 추가할 producer 상한 |
| `max_hops` | producer chain을 따라갈 깊이 |
| `action_priority` | producer-like action ordering 옵션 |

Helper는 required `kind=data` consume field만 확장합니다. context, auth, paging,
search filter는 execution catalog를 폭발시키면 안 됩니다.

## Output

반환값은 ordered tool name list입니다. 원래 candidate가 먼저 남고 그 뒤에 producer
candidate가 붙습니다.

```python
[
    "cancelOrder",
    "searchOrders",
    "getOrderDetail",
]
```

## Safety Policy

Expansion은 LLM catalog를 과하게 늘리지 않으면서 planning을 도와야 합니다.
low-confidence structural edge는 graph inspection에는 남기되, execution-oriented
candidate에는 strong evidence를 우선합니다.

권장 기본값:

| Setting | Guidance |
| --- | --- |
| `max_hops` | 일반 retrieval은 `1`, target-specific planning에서만 더 크게 |
| `max_producers_per_field` | `1`에서 `3` |
| Manual edge | deterministic contract evidence로 표현하기 어려울 때만 |
| Trace edge | 단일 observed run이 아니라 promoted 상태만 |

## Failure Modes

| 증상 | 가능한 원인 | 조치 |
| --- | --- | --- |
| expanded tool이 너무 많음 | broad required field 또는 높은 `max_hops` | hop/producer limit 낮추기 |
| producer가 추가되지 않음 | `produces` metadata 부족 | IO contract 확인 |
| wrong producer가 추가됨 | weak semantic tag | semantic build 또는 alias 보강 |
| LLM에 helper tool이 노출됨 | source catalog에 non-user tool 포함 | collection build 단계에서 filter |

## Validation

Candidate expansion은 list size만 보지 말고 plan outcome으로 검증합니다. 좋은 expansion은
평균 candidate count를 크게 늘리지 않으면서 `unsatisfied_field` failure를 줄입니다.

추적할 값:

- average candidate count
- max candidate count
- plan hit rate
- `unsatisfied_field` count
- selector ambiguity count

## 관련 문서

- [IO Contracts](../build/io-contracts.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
- [Target Selection](./target-selection.md)
