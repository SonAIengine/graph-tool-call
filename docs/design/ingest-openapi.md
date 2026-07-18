# OpenAPI Ingest — 설계 문서

**WBS**: 1-3
**파일**: `ingest/openapi.py`
**선행**: 1-2 (Spec Normalization)

## 파이프라인

```
입력 (URL/파일/dict)
  │
  ├─ 1. 로딩: URL fetch / file read / dict 직접
  ├─ 2. 파싱: JSON or YAML → dict
  ├─ 3. 정규화: normalizer.normalize(spec) → NormalizedSpec
  ├─ 4. $ref resolution: recursive dereference
  ├─ 5. Operation 추출: paths → operation 목록
  ├─ 6. 변환: operation → ToolSchema
  ├─ 7. 필터링: deprecated 제외, required-only 옵션
  └─ 8. Auto-categorize: tag/path → category 자동 생성
```

## Operation → ToolSchema 변환 규칙

### tool name 결정

```
우선순위:
1. operationId 있으면 → 그대로 사용
2. 없으면 → "{method}_{path_slug}" 생성
   예: GET /pets/{petId} → "get_pets_petId"
3. 충돌 시 → 숫자 접미사 "_2", "_3"
```

### parameters 매핑

| OpenAPI 위치 | ToolParameter 매핑 |
|-------------|-------------------|
| `in: path` | required=True, metadata.in="path" |
| `in: query` | required=spec에 따름, metadata.in="query" |
| `in: header` | metadata.in="header" (선택적 포함) |
| `requestBody` | 스키마 properties 각각 → parameter |

### 대형 requestBody 처리

```python
# 옵션: required_only=True (기본 False)
# Stripe payment_methods: 60개 필드 중 required만 노출
if required_only:
    params = [p for p in all_params if p.required]
```

### response schema 보존

dependency detection에 필요하므로 metadata에 저장:

```python
metadata["response_schema"] = {
    "200": {"id": "integer", "name": "string", ...}
}
```

### 실행 contract metadata

`metadata["openapi"]`는 XGEN 같은 실행 adapter가 HTTP 요청을 정확하게 렌더링하고
실패를 설명할 수 있도록 operation-level 정보를 additive로 보존한다.

| 키 | 의미 |
|---|---|
| `parameters` | path/query/header/cookie parameter, `style`, `explode`, `allowReserved`, default/example/constraint |
| `request_body` | 선택된 content type, 전체 content type 후보, 후보별 field, schema, top-level field, leaf field, body examples |
| `response` | 선택된 2xx/default response의 status, content type, schema, description, leaf field |
| `responses` | 모든 response status의 compact catalog: success flag, content types, examples, field count |
| `error_responses` | non-2xx response만 모은 실패 처리용 catalog |
| `security` | OpenAPI security requirements와 static scheme 정보. runtime token/cookie 값은 보존하지 않음 |

`HttpExecutor`는 이 metadata를 사용해 query/path/header/cookie parameter의
OpenAPI serialization 규칙(`style`, `explode`, `allowReserved`)을 반영한다.
request body는 `application/json`, `application/x-www-form-urlencoded`,
`multipart/form-data`를 렌더링하며, binary/file-like 인자가 있고 multipart
후보가 선언되어 있으면 multipart를 선택한다.
`validate_request(tool, params)`는 네트워크 호출 없이 `valid`,
`missing_required`, `missing_security`, `invalid_arguments`,
`unused_arguments`, `used_arguments`, `selected_content_type`을 반환한다.
기본적으로 required input이나 선언된 security credential이 빠져 있거나,
제공된 argument가 enum/type/범위/길이/pattern/array/object constraint를
위반하면 `build_request()`/`execute()`가 `OpenAPIRequestValidationError`를
발생시킨다. `apiKey` security scheme은 query/header/cookie argument 또는
executor header/cookie로 충족할 수 있고, bearer/basic/OAuth/OpenID Connect
계열은 `Authorization` header로 판정한다. XGEN은 이 diagnostics를
missing-field/auth/value popup과 resume target에 그대로 사용할 수 있다.
서버 coercion에 맡겨야 하는 기존 통합은 `validate_values=False`로 value
blocking만 끄고, `validate_request()` diagnostics는 계속 확인할 수 있다.
`execute()` 결과에는 기존 `status`/`headers`/`body`에 더해 `ok`,
`content_type`, `response_metadata`, 실패 시 `error_response`가 붙는다.
`response_metadata`는 exact status, `2XX` range, `default` 순서로
`metadata.openapi.responses`에서 매칭된다.

`metadata["api_contract"]`는 graph/search/plan용 raw produces/consumes leaf를 보존한다.
plain ingest 단계에서는 이 raw field들을 top-level `metadata.produces` /
`metadata.consumes`로 직접 올리지 않는다. large Swagger에서는 `status`, `data`,
`list` 같은 wrapper field가 많아 검색 ranking을 오염시킬 수 있기 때문이다.

## Auto-categorization

```python
def auto_categorize(tools, spec):
    """tag 또는 path prefix 기반 자동 카테고리 생성."""
    for tool in tools:
        tags = tool.metadata.get("tags", [])
        if tags:
            # tag 기반
            for tag in tags:
                assign_category(tool, tag)
        else:
            # path prefix fallback
            path = tool.metadata["path"]
            prefix = path.strip("/").split("/")[0]  # "/pets/{id}" → "pets"
            assign_category(tool, prefix)
```

## 인터페이스

```python
def ingest_openapi(
    source: str | Path | dict,
    *,
    required_only: bool = False,
    skip_deprecated: bool = True,
    include_headers: bool = False,
) -> tuple[list[ToolSchema], NormalizedSpec]:
    """OpenAPI spec → ToolSchema 목록 + 정규화된 spec."""
```
