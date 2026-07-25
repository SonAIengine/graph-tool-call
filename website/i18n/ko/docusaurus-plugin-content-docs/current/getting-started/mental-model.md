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
