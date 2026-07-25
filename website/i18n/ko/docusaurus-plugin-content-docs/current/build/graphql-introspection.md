---
sidebar_position: 2
title: GraphQL 인트로스펙션
description: GraphQL 인트로스펙션 응답을 검색하고 실행할 수 있는 도구로 변환합니다.
---

# GraphQL 인트로스펙션

GraphQL 인트로스펙션은 스키마가 제공하는 query, mutation, subscription
필드를 설명합니다. `graph-tool-call`은 각 루트 필드를 인자 스키마, 결과
스키마, 그래프 근거, 변수 기반 operation document를 갖춘 도구로 변환합니다.

## 스키마 등록

```python
from graph_tool_call import ingest_graphql_introspection

result = ingest_graphql_introspection(
    introspection_response,
    endpoint_url="https://api.example.com/graphql",
)

print(result.ready)
print([tool.name for tool in result.tools])
```

`ingest_source()`는 표준 `data.__schema`와 `__schema` 형식을
`graphql-introspection`으로 자동 감지합니다.

## endpoint를 따로 받는 이유

GraphQL 인트로스펙션 스키마에는 서비스 endpoint가 없습니다. 실행 가능한
catalog가 필요하면 endpoint를 명시해야 합니다. endpoint가 없어도 스키마와
도구는 확인할 수 있지만 결과에는 `graphql_endpoint_required` blocker가
남습니다.

endpoint는 userinfo 인증정보, 민감 query parameter, fragment가 없는 절대
HTTP(S) URL이어야 합니다. 실행 시 사용하는 인증정보는 애플리케이션의 auth
adapter에서 관리합니다.

## 생성되는 계약

`Query.customer(id: ID!): Customer` 같은 필드에서는 다음을 생성합니다.

- 도구 이름 `query_customer`
- 필수 입력 `id`
- 안정적인 변수 기반 operation document
- variables와 `data.customer` 응답 JSON Schema
- `api_contract.produces/consumes` 근거
- endpoint, body template, result path를 가진 `metadata.execution`
- read-only MCP annotation

mutation은 보수적으로 destructive로 표시합니다. subscription은 검색할 수
있지만 애플리케이션이 WebSocket 또는 SSE transport를 제공하기 전까지
`graphql_subscription_transport_required`를 보고합니다.

## 책임 경계

라이브러리는 인트로스펙션 요청을 직접 보내거나 인증정보를 저장하거나
고객사 endpoint를 선택하지 않습니다. XGEN, 브라우저 확장 또는 다른
애플리케이션이 네트워크 접근, 인증, 저장, 실행 헤더 전달을 담당합니다.
