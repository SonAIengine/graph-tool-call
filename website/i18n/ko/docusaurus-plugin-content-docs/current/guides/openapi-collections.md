---
title: OpenAPI 컬렉션
description: 대형 OpenAPI surface를 검색, plan, 실행 가능한 tool graph artifact로 빌드하는 방법을 설명합니다.
---

# OpenAPI 컬렉션

Agent가 큰 API surface를 검색하고 실행해야 한다면 OpenAPI collection을 사용합니다.

OpenAPI collection은 단순한 HTTP endpoint 목록이 아니라 build artifact로 다뤄야 합니다.
쓸모 있는 artifact에는 tools, contracts, semantic metadata, graph edges, readiness
diagnostics, validation results가 함께 들어갑니다.

## 권장 Build Pipeline

1. OpenAPI source를 로드합니다.
2. operation contract를 추출합니다.
3. semantic action/resource/module metadata를 파생합니다.
4. structure, contract, curated evidence에서 graph edge를 만듭니다.
5. readiness report를 생성합니다.
6. 실행을 열기 전에 search와 planning quality case를 돌립니다.

## 최소 Build

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

애플리케이션 저장소에는 artifact 전체를 보존하고, source refresh나 rebuild 시 unknown
field를 삭제하지 않는 방식으로 업데이트해야 합니다.

## Artifact Section

| Section | 목적 |
| --- | --- |
| `tools` | 정규화된 operation tool schema |
| `edges` | structural, contract, semantic, manual, trace graph edge |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | graph edge의 evidence 분포 |
| `readiness_report` | deterministic OpenAPI readiness 진단 |
| `metadata` | version과 build context |

## Readiness Report

`analyze_openapi_collection()`은 collection이 search, planning, execution에 준비됐는지
보고합니다.

안정 issue code 예시는 다음과 같습니다.

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

## Contract Index

Adapter가 내부 OpenAPI parser helper에 의존하지 않고 operation-level fact를 얻어야 할
때는 `extract_openapi_contract_index()`를 사용합니다.

```python
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")
for operation in index["operations"]:
    print(operation["method"], operation["path"], operation["operationId"])
```

## Adapter 책임

엔진은 product-neutral evidence를 만듭니다. 애플리케이션은 다음을 책임집니다.

- DB row와 collection lifecycle
- auth profile과 runtime session header
- readiness, graph, Quality Lab result UI
- 안전한 실행 정책
- 수동 operator override
- rebuild 시 `quality_lab`, `trace_edges`, `learning` metadata 보존

## 실행으로 승격하기

ingestion이 성공했다는 이유만으로 execution을 열지 않습니다. 최소한 다음이 필요합니다.

- readiness report에 blocker issue가 없음
- search Quality Lab suite 통과
- target selector diagnostic이 UI/로그에서 확인 가능
- 대표 workflow plan case 통과
- auth readiness 설정
- write API에 대한 mutation safety policy

## 관련 문서

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Quality Lab](../validation/quality-lab.md)
