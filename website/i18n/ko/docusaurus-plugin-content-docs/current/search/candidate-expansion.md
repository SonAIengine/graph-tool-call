---
title: 후보 확장
description: evidence가 있는 경우 retrieved target에 producer tool과 graph neighbor를 확장합니다.
---

# 후보 확장

Candidate expansion은 initial search 이후 관련 tool을 추가합니다. 가장 중요한
확장은 producer discovery입니다. target이 required field를 소비한다면, graph는
그 field를 생산하는 tool을 포함할 수 있습니다.

## Expansion Sources

- deterministic IO contract edge
- OpenAPI link
- manual edge
- promoted run-observed trace edge
- high-confidence semantic link

## Safety Policy

Expansion은 LLM catalog를 과하게 늘리지 않으면서 planning을 도와야 합니다.
low-confidence structural edge는 graph inspection에는 남기되, execution-oriented
candidate에는 strong evidence를 우선합니다.

## 관련 문서

- [IO Contracts](../build/io-contracts.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
