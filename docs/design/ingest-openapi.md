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
1. operationId 있으면 → unique할 때 그대로 ToolSchema.name으로 사용
2. 없으면 → normalizer가 "{method}_{path_slug}"를 생성
   예: GET /pets/{petId} → "get_pets_by_petId"
3. 같은 operationId가 여러 번 나오면 → 첫 번째는 원래 이름 유지, 이후는
   deterministic method/path suffix 부여
   예: findOrder, findOrder__get_orders_by_orderId
```

원본 OpenAPI `operationId`는 항상 `metadata.openapi.operation_id`에 보존한다.
dedupe된 경우 `metadata.openapi.operation_id_duplicate=true`,
`operation_id_duplicate_count`, `operation_id_duplicate_index`,
`operation_id_deduped_name`을 함께 기록한다. OpenAPI Link Object에서
duplicate `operationId`를 직접 가리키면 ambiguous하므로 graphify는 안전하게
연결하지 않는다. 같은 duplicate group 안의 정확한 target은 `operationRef`로
해결한다.

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
| `request_body` | 선택된 content type, 전체 content type 후보, 후보별 field, schema, top-level field, leaf field, body examples, example-inferred fields |
| `response` | 선택된 2xx/default response의 status, content type, schema, description, leaf field, response header, envelope metadata |
| `responses` | 모든 response status의 compact catalog: success flag, content types, examples, headers, field count. 숫자 2xx와 `2XX` range는 success, `4XX`/`5XX`와 `default`는 failure metadata로 분류 |
| `error_responses` | non-2xx response만 모은 실패 처리용 catalog |
| `server` | operation/path/spec 우선순위로 선택된 OpenAPI server metadata. variables default를 확장한 URL과 raw URL template, enum/default 정보를 함께 보존 |
| `security` | OpenAPI security requirements와 static scheme 정보. runtime token/cookie 값은 보존하지 않음 |

root JSON array, primitive body, opaque map/object body처럼 top-level property가
없는 request body는 synthetic `body` slot으로 노출한다.
`metadata.openapi.request_body.root.request_body_root=true`와 `json_path="$"`를
기록하고, array item leaf는 `$[*].field` 형태로 graph/plan contract에 계속
남긴다. executor는 root array body에서 `{"body": [...]}`를 raw JSON으로
전송하고, 단일 item 실행 편의를 위해 `$[*].field` leaf argument만 주어져도
`[{"field": value}]` 형태로 조립한다.
object body 안의 required container field도 leaf argument로 채워질 수 있다.
예를 들어 `items`가 required array이고 `$.items[*].goodsNo`,
`$.items[*].quantity` leaf만 들어오면 preflight는 `items`를 누락으로 보지 않고,
executor는 `{"items": [{"goodsNo": "...", "quantity": 1}]}` 형태로 전송한다.

OpenAPI server URL은 실행 정확도에 직접 영향을 준다. `servers[].variables`가
있으면 `default` 값을 적용한 URL을 `metadata.base_url`로 사용하고, 원본
template과 variable enum/default/description은 `metadata.openapi.server`에
남긴다. 우선순위는 OpenAPI 규칙대로 operation `servers` → path item
`servers` → spec-level `servers`이며, Swagger 2.0은 `schemes + host +
basePath`를 같은 server metadata shape로 정규화한다.

선언된 OpenAPI `security` requirement는 `metadata.openapi.security`에 원형에
가까운 compact metadata로 남기고, 동시에 `metadata.api_contract.consumes`에는
`kind=auth` row로 올린다. `apiKey` scheme은 선언된 query/header/cookie
credential 이름을 사용하고, bearer/basic/OAuth/OpenID Connect 계열은
`Authorization` credential로 표현한다. 이 row는 `required=false`,
`security_required=true`로 유지해 Planflow가 토큰을 사용자 입력이나 producer
chain으로 만들지 않게 하고, 실제 누락 차단은 `HttpExecutor.validate_request`와
XGEN 실행 adapter가 담당한다.

성공 response의 선언된 header는 `metadata.openapi.responses[].headers`와
선택된 `metadata.openapi.response.headers`에 보존하고, graph/search/plan용
`metadata.api_contract.produces`에는 `location=response_header`,
`json_path=$.headers.<Name>` row로 추가한다. OpenAPI Link Object가
`$response.header.X-Session-Token`처럼 header 값을 다음 operation parameter로
연결하면 graphify는 `openapi_link` evidence와 producer alias를 만들어
Planflow가 `${s1.headers.X-Session-Token}` 형태로 바인딩할 수 있게 한다.

OpenAPI status range도 contract 단계에서 보존한다. `2XX` response는 명시
숫자 2xx response가 없을 때 selected success response로 쓰이고,
`api_contract.produces`의 원천이 될 수 있다. `4XX`/`5XX` range와 `default`는
`metadata.openapi.error_responses`에 남겨 XGEN 실패 UI/log가 정확한 실패
계약을 보여줄 수 있게 한다.

OpenAPI `readOnly`/`writeOnly` 방향성도 contract 추출 전에 반영한다.
request body의 `readOnly` field는 tool parameter, `request_body.fields`,
`api_contract.consumes`에서 제외하고, response의 `writeOnly` field는
`response.fields`, `api_contract.produces`에서 제외한다. 반대로 `writeOnly`
request field와 `readOnly` response field는 그대로 보존해 XGEN이 해당 값의
방향성을 설명하거나 로그에 남길 수 있게 한다. nested object/array leaf는
부모의 `readOnly`/`writeOnly`/`deprecated` hint를 상속한다.

nullable dialect는 contract 추출 전에 하나의 의미로 정규화한다. OpenAPI
`nullable`, Swagger `x-nullable`, JSON Schema `type: ["T", "null"]`,
`anyOf`/`oneOf` + `null` 단일 union은 모두 `nullable=true`로 보존한다.
JSON body에서 사용자가 명시적으로 `None`을 준 경우 nullable field는 `null`로
직렬화하고, non-nullable field는 missing이 아니라 `reason=null` invalid
diagnostic으로 보고한다.

Spring/SpringDoc 계열 Swagger에서 query DTO가 `searchRequest` 같은
`type=object` parameter로 노출되는 경우, wrapper 자체를 tool input이나
graph consume field로 쓰지 않고 내부 `brandNo`, `goodsNo`, `saleStatusCd`
같은 실제 query field로 펼친다. wrapper와 sibling field가 함께 노출되면
sibling field를 우선하고 wrapper는 제거한다. 이 규칙은 `ToolParameter`,
`metadata.openapi.parameters`, `input_locations`, `api_contract.consumes`에
동일하게 적용되어 검색/Planflow/executor가 같은 field universe를 보게 한다.
단, 명시적인 `style=deepObject` parameter는 `filter[status]=paid`처럼 wrapper
이름이 wire format의 일부이므로 펼치지 않고 wrapper를 유지한다.

OpenAPI3 Parameter Object가 `schema` 대신 `content`를 사용하는 경우에도
선택된 media type, schema field, example field를 보존한다. JSON content
parameter는 `content_type`, `content_schema_type`, `content_fields`,
`content_types`를 `metadata.openapi.parameters`와 `api_contract.consumes`에
남기며, executor는 object/list 값을 하나의 JSON 문자열 parameter로 직렬화한다.
이 경우 parameter 이름 자체가 wire format의 입력이므로 query DTO 펼침 규칙을
적용하지 않는다.

JSON Schema `additionalProperties`는 동적 key map으로 보존한다. map value가
object면 내부 field를 `$.data.*.goodsNo` 같은 path로 추출하고
`additional_properties=true`, `map_value=true`, `map_key_placeholder="*"`를
붙인다. primitive map이면 `$.labels.*`처럼 parent field 이름을 유지한다.
Planflow v1에서 `*`는 fan-out이 아니라 key 문자열 정렬 기준 첫 map value
선택이다. request body 생성 시 map value leaf path는 직접 assignment 후보에서
제외해 `*`가 literal JSON key로 들어가지 않도록 한다.

`oneOf`/`anyOf` schema는 첫 번째 branch만 선택하지 않고 모든 object branch의
field를 union으로 추출한다. branch 안에서만 required인 field는
`required_in_branch=true`, `schema_combinator`, `schema_branch`,
`schema_branches` metadata를 남기되 전역 `required=true`로 승격하지 않는다.
`allOf` 안에 들어있는 `oneOf`/`anyOf`도 공통 field와 branch field를 모두 보존한다.
`discriminator.propertyName`과 mapping, branch-local `const`/single-value enum은
`discriminator_property`, `discriminator_value`, `discriminator_values`,
`schema_ref`, `const`로 보존한다. discriminator field가 branch schema에 직접
없어도 mapping 값으로 synthetic top-level field를 만들어 request body 렌더링과
diagnostics에서 variant 선택 근거를 잃지 않는다.
이렇게 해야 결제수단/배송방식처럼 대안 body schema를 가진 API에서 tool graph와
request validation이 서로 다른 branch field를 동시에 요구하지 않는다.

응답 schema가 `code/message/data`, `status/result`, `payload` 같은 wrapper를
가진 경우 `metadata.openapi.response.envelope`에 `wrapper_path`,
`collection_path`, `item_path`, `metadata_fields`를 기록한다. 각 response field와
`api_contract.produces` row에는 `response_envelope_path`,
`response_collection_path`, `response_item_path`, `value_path_aliases`를 additive로
붙인다. canonical `json_path`는 OpenAPI schema 기준으로 유지하고,
`value_path_aliases`는 runtime adapter가 raw body, `{"body": ...}` wrapper,
혹은 envelope-unwrapped item/list를 반환할 때 produced value를 회수하기 위한
fallback 경로로만 사용한다.

OpenAPI Response Object의 `links`는 response catalog와 `api_contract.links`에
보존한다. link parameter가 `$response.body#/id`나 `$response.header.X-Trace-Id`
같은 runtime expression을 사용하면 `source`, `json_path`/`header`, target
parameter name을 구조화해 남긴다. graphify는 success response link를
`openapi_link` evidence edge로 승격하고, `$response.body#/id -> userId`처럼
생산 field 이름과 소비 field 이름이 다른 경우 producer alias를 만들어
PathSynthesizer가 추측 없이 `${producer.id}` binding을 만들 수 있게 한다.

schema가 `type: object`처럼 generic하거나 field가 누락됐지만 request/response
example이 실제 payload를 담고 있으면 example을 leaf row로 순회해 contract를
보강한다. 이 row는 `schema_inferred_from=example`, `example_source`,
`example_name`, `example_content_type`, `example_status`를 포함할 수 있다. 예시는
관측 근거이지 schema 규칙은 아니므로 `required=false`로 보존하고, 명시 schema와
같은 `(field_name, json_path)`가 있으면 schema row에 example hint만 merge한다.
request body example의 top-level field는 ToolParameter fallback으로도 쓰기 때문에,
generic schema만 있는 API에서도 LLM이 `keyword`, `filters` 같은 body argument
이름을 볼 수 있고 `HttpExecutor`가 leaf `json_path`를 사용해 nested JSON body를
구성할 수 있다.

`HttpExecutor`는 이 metadata를 사용해 query/path/header/cookie parameter의
OpenAPI serialization 규칙(`style`, `explode`, `allowReserved`)을 반영한다.
`style=deepObject` query object는 `filter[status]=SALE` 같은 1-depth 필드뿐
아니라 `filter[range][minPrice]=1000` 같은 nested object도 bracket notation으로
재귀 직렬화한다. primitive array는 같은 bracket field를 반복하고, object array는
`filter[sort][0][field]=createdAt`처럼 index를 붙여 deterministic하게 보낸다.
request body는 `application/json`, `application/x-www-form-urlencoded`,
`multipart/form-data`를 렌더링하며, binary/file-like 인자가 있고 multipart
후보가 선언되어 있으면 multipart를 선택한다.
OpenAPI `requestBody.content[media].encoding`은 field-level
`encoding_content_type`, `encoding_style`, `encoding_explode`,
`encoding_allow_reserved`, `encoding_headers`, `encoding_field_name`으로 보존한다.
form-urlencoded body는 명시된 field encoding serialization을 따르고,
multipart body는 field별 part `Content-Type`과 static/default/example part
header를 반영한다. multipart object part의 leaf argument만 들어온 경우에도
`$.metadata.title`, `$.metadata.category` 같은 경로를 다시 `metadata` JSON part로
묶어 전송하므로, Planflow가 graph contract의 leaf field를 바인딩해도 실제 wire
format은 OpenAPI top-level part 구조를 유지한다.
그 외 `text/plain`, `application/octet-stream` 같은 request body media type은
JSON wrapper를 만들지 않고 synthetic root `body` slot 또는 단일 body argument를
raw bytes로 전송한다. 문자열은 UTF-8 bytes로, bytes/file-like 값은 원문 bytes로
보존한다.
OpenAPI parameter/body의 `default`와 JSON Schema `const`는 caller가 해당
non-path input을 생략했을 때 executable default로 적용한다. 명시적으로 들어온
argument는 덮어쓰지 않고, 선언된 `apiKey` security credential이나
`Authorization`, `access_token`, `X-Api-Key` 같은 credential-like 이름에는
적용하지 않으며, `example`은 실행값으로 사용하지 않는다. 적용된 값은
`applied_defaults` diagnostic에 location/source/value와 함께 남긴다.
`validate_request(tool, params)`는 네트워크 호출 없이 `valid`,
`missing_required`, `missing_security`, `invalid_arguments`,
`unused_arguments`, `used_arguments`, `selected_content_type`,
`applied_defaults`를 반환한다.
기본적으로 required input이나 선언된 security credential이 빠져 있거나,
제공된 argument가 enum/type/범위/길이/pattern/array/object constraint를
위반하면 `build_request()`/`execute()`가 `OpenAPIRequestValidationError`를
발생시킨다. discriminator 값이 제공된 request body는 선택된 branch의
`required_in_branch` 필드만 `request_body_branch` missing diagnostic으로
보고하고, 다른 branch 전용 field가 함께 제공되면
`reason=discriminator_branch` invalid diagnostic으로 보고한다. Required/value
validation과 branch diagnostic은 leaf argument와 explicit raw JSON `body`
payload 모두에 적용된다. Root array body나 object 안의 nested array도
`$[*].quantity`, `$.items[*].goodsNo` 같은 wildcard JSON path를 기준으로
item별 required/value constraint를 preflight에서 검사한다. JSON object request
body는 schema field 이름이 `body`가 아닐 때 executor에 raw `body` object로
전달할 수도 있다. `apiKey`
security scheme은 query/header/cookie argument 또는 executor header/cookie로
충족할 수 있고, bearer/basic/OAuth/OpenID Connect 계열은 `Authorization`
header로 판정한다. XGEN은 이 diagnostics를 missing-field/auth/value popup과
resume target에 그대로 사용할 수 있다.
서버 coercion에 맡겨야 하는 기존 통합은 `validate_values=False`로 value
blocking만 끄고, `validate_request()` diagnostics는 계속 확인할 수 있다.
`execute()` 결과에는 기존 `status`/`headers`/`body`에 더해 `ok`,
`content_type`, `response_metadata`, schema-guided `body_view`, 실패 시
`error_response`가 붙는다.
`response_metadata`는 exact status, `2XX` range, `default` 순서로
`metadata.openapi.responses`에서 매칭된다. `body_view`는 raw `body`를
변경하지 않고, `metadata.openapi.response.envelope`의 `wrapper_path`나
`collection_path`가 실제 응답에 존재할 때 `body_view.value`에 payload 또는
collection item list를 담는다. Plan repair/entity extraction은
`body_view.value`도 produced value 후보로 사용한다.

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
