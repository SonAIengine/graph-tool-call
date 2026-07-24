# OpenAPI 컬렉션

Agent가 큰 API surface를 검색하고 실행해야 한다면 OpenAPI collection을 사용합니다.

## 권장 Build Pipeline

1. OpenAPI source를 로드합니다.
2. operation contract를 추출합니다.
3. semantic action/resource/module metadata를 파생합니다.
4. structure, contract, curated evidence에서 graph edge를 만듭니다.
5. readiness report를 생성합니다.
6. 실행을 열기 전에 search와 planning quality case를 돌립니다.

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

