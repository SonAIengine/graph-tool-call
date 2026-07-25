---
title: Readiness Diagnostics
description: API collection이 search, planning, execution에 준비됐는지 진단합니다.
---

# Readiness Diagnostics

Readiness diagnostics는 API collection이 tool graph search나 Planflow execution에
아직 적합하지 않을 때 deterministic한 피드백을 제공합니다.

OpenAPI ingest 직후와 source refresh 이후에 이 report를 다시 확인합니다. 이 진단은
의도적으로 LLM-free입니다. 같은 spec과 option이면 같은 status, score, issue code,
recommendation이 나와야 합니다.

## Public API

```python
from graph_tool_call.analyze import analyze_openapi_collection

report = analyze_openapi_collection("openapi.json")
print(report.summary.readiness_score)
print(report.summary.status)
```

이미 build된 graph에서는 source를 다시 ingest하지 않고 convenience method를 사용할 수
있습니다.

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("openapi.json")
report = graph.analyze_openapi()
```

## Report Shape

| Section | 답하는 질문 |
| --- | --- |
| `summary` | tool 수, duplicate/deprecated 수, 최종 readiness score |
| `coverage` | request/response schema, contract field, enum, auth field, envelope candidate 검출 여부 |
| `graph_readiness` | operation이 유용한 evidence로 연결되어 있는지, isolated 상태인지 |
| `issues` | severity, code, tool, evidence, recommendation을 가진 안정 issue record |
| `recommendations` | plan/execute를 열기 전에 해야 할 보완 조치 |

이 report는 product artifact에 저장하고, UI에 보여주고, quality gate output에 붙이는
용도로 설계되어 있습니다.

## Stable Issue Codes

- `missing_request_schema`
- `generic_request_body`
- `missing_response_schema`
- `duplicate_operation_id`
- `missing_operation_id`
- `auth_required`
- `unsupported_content_type`
- `array_leaf_alignment_required`
- `response_envelope_detected`
- `low_graph_connectivity`
- `no_contract_fields`
- `semantic_action_unknown_rate_high`
- `semantic_resource_unassigned_rate_high`
- `weak_edge_evidence`
- `module_cluster_too_large`

## Issue Record

각 issue는 단순 log message가 아니라 diagnostic record로 다뤄야 합니다.

```json
{
  "severity": "warning",
  "code": "missing_response_schema",
  "tool": "getOrderList",
  "message": "No usable response schema was found.",
  "evidence": {"method": "GET", "path": "/orders"},
  "recommendation": "Add a response schema or repair the source contract."
}
```

product adapter는 unknown field를 보존해야 합니다. 그래야 새 engine version이 diagnostic
field를 추가해도 오래된 stored report와 호환됩니다.

## Status Policy

- `ready`: score가 높고 blocker가 없음
- `warning`: 사용할 수 있지만 알려진 약점이 있음
- `blocked`: search, planning, execution 결과가 오해를 만들 수 있음

기본 score policy는 100점에서 시작해 blocker/warning issue에 따라 감점하고 `0..100`
범위로 clamp합니다. blocker가 있으면 numeric score가 괜찮아 보여도 `blocked`로
간주해야 합니다.

## 해석 방법

| Signal | 의미 | 일반적인 조치 |
| --- | --- | --- |
| 낮은 response coverage | 검색은 되지만 plan/execution이 결과 field를 모를 수 있음 | response schema repair 또는 contract metadata 보강 |
| 높은 semantic unknown rate | search/selector가 action/resource signal을 약하게 봄 | generic alias 전달 또는 metadata curate |
| 낮은 graph connectivity | candidate expansion이 producer/consumer를 찾기 어려움 | contract field와 edge evidence 점검 |
| auth required | 실행에는 adapter-side auth profile/session 처리가 필요 | live execution 전에 auth readiness 설정 |
| envelope candidate | response data가 `data`, `result` 같은 wrapper 아래 있을 수 있음 | planning 전 body view extraction 확인 |

## Adapter Pattern

```python
report = analyze_openapi_collection(
    source,
    context_field_names={"mallNo", "siteNo"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchType"},
)

if report.summary.status == "blocked":
    disable_execute_for_collection()
else:
    save_report(report.to_dict())
```

product naming convention은 adapter가 option으로 넘깁니다. engine에는 특정 product의
`mallNo`, `siteNo` 같은 이름을 하드코딩하지 않습니다.

## 검증

OpenAPI parsing, semantic build, edge quality logic이 바뀌면 readiness test를 실행합니다.

```bash
poetry run pytest tests/test_openapi_readiness.py -q
```

문서 build에서는 issue code term이 검색 가능한지 확인합니다.

```bash
cd website
npm run build
```

## 관련 문서

- [OpenAPI Ingestion](./openapi-ingestion.md)
- [Collection Artifacts](./collection-artifacts.md)
- [Auth Readiness](./auth-readiness.md)
- [Quality Lab](../validation/quality-lab.md)
