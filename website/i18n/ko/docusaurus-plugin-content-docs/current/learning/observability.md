---
title: Trace 관측성
description: 검색, 선택, dependency, token budget 결정을 재생하고 필요하면 OpenTelemetry로 내보냅니다.
sidebar_position: 5
---

# Trace 관측성

컬렉션이 잘못된 도구를 반환했을 때 단순히 “무엇이 1위였는가”만으로는
원인을 찾기 어렵습니다. 다음 정보가 함께 필요합니다.

- 어떤 score channel이 각 후보의 순위를 움직였는가
- LLM target을 유지했는가, deterministic selector가 보정했는가
- 어떤 선행 producer가 dependency로 확장됐는가
- model token budget 안에 어떤 schema가 들어가고 빠졌는가
- 어느 단계가 latency를 사용했는가

Observability API는 이 답을 하나의 버전된 secret-scrubbed trace로
기록합니다. 엔진의 검색이나 선택 결과는 바꾸지 않습니다.

## 파이프라인 기록

```python
from graph_tool_call.graphify import retrieve_graphify, select_target_candidate
from graph_tool_call.observability import (
    STAGE_RETRIEVAL,
    STAGE_TARGET_SELECTION,
    TraceRecorder,
    record_retrieval_result,
    record_selector_result,
)

trace = TraceRecorder("catalog_request", attributes={"query": query})

with trace.start_span(STAGE_RETRIEVAL, "retrieve_graphify") as span:
    retrieval = retrieve_graphify(graph, query, top_k=8, include_evidence=True)
    record_retrieval_result(span, retrieval)

with trace.start_span(STAGE_TARGET_SELECTION, "select_target_candidate") as span:
    selection = select_target_candidate(
        query,
        [row["name"] for row in retrieval["results"]],
        graph.tools,
        retrieval_results=retrieval["results"],
    )
    record_selector_result(span, selection)

trace.write("trace.json")
```

각 candidate와 schema decision에는 `outcome`, 가능한 경우 rank/score,
evidence, 그리고 최소 한 개의 `reason_code`가 들어갑니다.

## 안전한 재생

```bash
graph-tool-call trace trace.json
graph-tool-call trace trace.json --json
```

Replay는 schema version `1.0`을 검증하고 stage 순서, latency, decision
outcome, reason coverage를 복원합니다. LLM이나 외부 API를 다시 호출하지
않습니다.

공통 scrub 정책은 credential 형태의 key, bearer/JWT 형태의 값, raw
body/payload/result, 이메일, 전화번호 형태 값을 가립니다. 기본 plan/runner
adapter는 raw argument와 output을 기록하지 않습니다.

## OpenTelemetry 내보내기

```bash
pip install "graph-tool-call[observability]"
```

```python
from graph_tool_call.observability import OpenTelemetryTraceExporter

OpenTelemetryTraceExporter().export(trace.finish())
```

OpenTelemetry SDK, sampling, batching, backend 설정은 host application이
소유합니다. graph-tool-call은 API만 설치하고 활성 tracer provider를
사용하므로 특정 collector나 telemetry vendor를 강제하지 않습니다.

## 저장 경계

Raw HTTP request/response 대신 scrubbed trace JSON만 저장하세요. Tool name과
field path도 내부 API 구조를 드러낼 수 있으므로 catalog artifact와 같은
접근 제어 및 보존 정책을 적용해야 합니다.
