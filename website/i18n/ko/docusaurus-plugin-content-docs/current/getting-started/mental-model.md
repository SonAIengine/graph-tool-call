---
title: Mental Model
description: LLM이 실행하기 전에 graph-tool-call이 작고 근거 있는 tool surface를 만드는 방식을 설명합니다.
---

# Mental Model

`graph-tool-call`은 대형 tool catalog를 위한 retrieval과 planning 엔진입니다.
LLM을 대체하지 않고, LLM이 판단하기 전에 더 작고, 더 잘 정렬되고, 근거가
보이는 tool 후보군을 준비합니다.

## Pipeline

1. OpenAPI, MCP, Python function 같은 원천을 ingest합니다.
2. 각 operation을 안정적인 `ToolSchema`로 정규화합니다.
3. request field, response field, auth requirement, semantic action/resource/module
   signal을 분석합니다.
4. structure, contract, manual evidence, 검증된 trace evidence로 graph edge를 만듭니다.
5. 현재 사용자 query에 맞는 compact candidate set을 검색합니다.
6. LLM target을 deterministic evidence로 guard하면서 최종 target을 선택합니다.
7. 필요한 producer, input, user slot, 실행 순서를 plan으로 만듭니다.
8. product adapter를 통해 tool을 실행하고 structured event를 stream합니다.
9. scrub된 성공/실패 trace를 검증한 뒤 learning suggestion으로 반영합니다.

## Artifact Flow

| Stage | Main Artifact | 저장 위치 |
| --- | --- | --- |
| ingest | `ToolSchema` | engine 또는 adapter |
| contract | `metadata.api_contract` | collection artifact |
| semantic build | `metadata.ai_metadata` | collection artifact |
| graph build | edges와 summary | collection artifact |
| retrieval | candidate row와 evidence | request trace 또는 Quality Lab |
| selection | `target_selector` diagnostic | plan metadata |
| execution | runner event | product trace/log |
| learning | scrubbed suggestion | collection-scoped learning state |

## Engine vs Adapter

엔진이 맡는 product-neutral 로직:

- schema normalization
- semantic metadata
- IO contract
- graph edge
- retrieval evidence
- target selection
- plan synthesis diagnostics
- learning suggestion

어댑터가 맡는 product-specific runtime:

- database row
- auth profile
- user session
- HTTP execution
- SSE transport
- UI workflow
- collection storage

## 왜 Graph인가

LLM tool catalog는 tool이 많고 설명이 느슨하면 쉽게 실패합니다. graph는 어떤
tool이 field를 만들고, 어떤 tool이 그 field를 소비하고, 어떤 operation이 같은
resource를 다루며, 어떤 path가 성공 실행에서 관찰됐는지를 명시합니다.

그 결과 prompt 안에 evidence를 숨기지 않고 검색, 점검, 검증, 개선할 수 있는
catalog가 됩니다.

## LLM의 역할

LLM은 여전히 중요합니다. 사용자 요청을 해석하고, compact catalog 안에서 선택하고,
자연어 gap을 채우고, 최종 응답을 작성합니다. 엔진은 LLM이 불필요한 catalog noise를
보지 않게 하고, target이나 plan이 왜 수용됐는지를 기록합니다.

첫 번째 최적화 대상은 model fine-tuning이 아닙니다. model이 받는 evidence를 좋게
만드는 것입니다. contract, semantic metadata, candidate ordering, 검증된 trace
suggestion을 먼저 개선합니다.

## Failure Handling

run이 실패하면 prompt를 고치기 전에 failure를 분류합니다.

- expected tool이 없으면 retrieval evidence가 약한 것입니다.
- final target이 틀리면 selector 또는 semantic metadata를 봐야 합니다.
- required field가 없으면 contract/default/user-slot mapping이 부족한 것입니다.
- auth failure는 adapter runtime context 문제입니다.
- downstream 4xx/5xx는 request construction 또는 API behavior를 봐야 합니다.

전체 목록은 [실패 분류](../plan/failure-taxonomy.md)를 참고하세요.
