# Spec Normalization Layer — 설계 문서

**WBS**: 1-2
**파일**: `ingest/normalizer.py`
**목적**: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1 → 통일된 내부 표현으로 정규화

## 왜 필요한가?

| 프레임워크 | 기본 생성 버전 | 고유 패턴 |
|-----------|--------------|----------|
| FastAPI | **3.1.0** | `anyOf: [{type:"string"},{type:"null"}]`, 자동 422 |
| NestJS | **3.0.0** | `nullable: true`, 빈 servers/description |
| springdoc v2 | **3.0.1** | JSR-303 → schema 제약조건 |
| springdoc v3 | **3.1.0** | Java 상속 → allOf |
| Go swag | **2.0** | `#/definitions/pkg.Type`, host+basePath |
| springfox | **2.0** | x-* 확장 필드 |

**3가지 버전을 각각 처리하는 것은 비효율** → 정규화 레이어에서 하나로 통일.

## 정규화 전략

```
입력 spec (dict)
    │
    ├─ detect_version()
    │   ├─ "swagger" 키 → SWAGGER_2_0
    │   ├─ "openapi" 시작 "3.0" → OPENAPI_3_0
    │   └─ "openapi" 시작 "3.1" → OPENAPI_3_1
    │
    ├─ normalize(spec) → NormalizedSpec
    │   ├─ Swagger 2.0 변환
    │   ├─ OpenAPI 3.1 → 3.0 다운그레이드
    │   └─ 공통 정규화
    │
    └─ 출력: OpenAPI 3.0 호환 내부 표현
```

**정규화 타겟**: OpenAPI 3.0 (가장 넓은 도구 호환성)

## 변환 상세

### 1. 버전 감지

```python
def detect_version(spec: dict) -> SpecVersion:
    if "swagger" in spec:
        return SpecVersion.SWAGGER_2_0
    openapi = spec.get("openapi", "")
    if openapi.startswith("3.1"):
        return SpecVersion.OPENAPI_3_1
    if openapi.startswith("3.0"):
        return SpecVersion.OPENAPI_3_0
    raise ValueError(f"Unsupported spec version: {openapi}")
```

### 2. Swagger 2.0 → OpenAPI 3.0

| Swagger 2.0 | OpenAPI 3.0 | 비고 |
|-------------|------------|------|
| `definitions` | `components.schemas` | $ref 경로도 변경 |
| `parameters` (top-level) | `components.parameters` | |
| `host` + `basePath` + `schemes` | `servers: [{url: "..."}]` | scheme + host + basePath 결합 |
| `securityDefinitions` | `components.securitySchemes` | |
| `produces` / `consumes` | operation-level `content` | media type 이동 |
| parameter `type` 직접 | parameter `schema: {type}` | schema 래핑 |
| parameter `in: "body"` | `requestBody` | body → requestBody 변환 |
| `x-nullable: true` | `nullable: true` | |

#### $ref 경로 변환

```python
def convert_ref(ref: str) -> str:
    """#/definitions/Model → #/components/schemas/Model"""
    if ref.startswith("#/definitions/"):
        name = ref.replace("#/definitions/", "")
        # Go swag의 "pkg.Type" → "PkgType" (dot 제거)
        name = name.replace(".", "")
        return f"#/components/schemas/{name}"
    return ref
```

#### body parameter → requestBody

```python
# Swagger 2.0
{"in": "body", "name": "body", "schema": {"$ref": "#/definitions/Pet"}}

# → OpenAPI 3.0
{"requestBody": {
    "required": true,
    "content": {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/Pet"}
        }
    }
}}
```

### 3. OpenAPI 3.1 → 3.0 다운그레이드

| OpenAPI 3.1 | OpenAPI 3.0 | 비고 |
|------------|------------|------|
| `anyOf: [{type:"string"},{type:"null"}]` | `type: "string", nullable: true` | FastAPI 핵심 패턴 |
| `type: ["string", "null"]` | `type: "string", nullable: true` | JSON Schema 호환 |
| `examples` (복수, 배열) | `example` (단수) | 첫 번째 값 사용 |
| `const` | `enum: [value]` | |
| `$ref` + sibling keywords | `allOf: [{$ref}, {siblings}]` | 3.1에서 $ref 옆 키워드 허용 |
| `contentMediaType` | 제거 (무시) | |

#### nullable 정규화 (3가지 패턴 통일)

```python
def normalize_nullable(schema: dict) -> dict:
    """3가지 nullable 패턴 → nullable: true 통일."""

    # 패턴 1: OpenAPI 3.1 — anyOf + null
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s != {"type": "null"}]
        if len(non_null) < len(schema["anyOf"]):
            # null이 포함되어 있었음
            if len(non_null) == 1:
                schema.update(non_null[0])
                schema["nullable"] = True
                del schema["anyOf"]
            # anyOf에 2개 이상 non-null → 그대로 유지 (진짜 union)

    # 패턴 2: JSON Schema — type 배열
    if isinstance(schema.get("type"), list):
        types = schema["type"]
        if "null" in types:
            non_null = [t for t in types if t != "null"]
            schema["type"] = non_null[0] if len(non_null) == 1 else non_null
            schema["nullable"] = True

    # 패턴 3: Swagger 2.0 확장
    if schema.pop("x-nullable", None):
        schema["nullable"] = True

    return schema
```

### 4. 공통 정규화 (버전 무관)

| 처리 | 설명 |
|------|------|
| 빈 description 제거 | `""` → 키 자체 제거 |
| 빈 servers 정리 | `[]` → 제거 |
| operationId 정규화 | 없으면 `{method}_{path_slug}` 생성 |
| deprecated 마킹 | `deprecated: true` → metadata에 저장 |
| x-* 확장 필드 | 무시하되 metadata에 보존 |

## 프레임워크별 edge case 처리

| 프레임워크 | Edge Case | 처리 방법 |
|-----------|----------|----------|
| FastAPI | 모든 endpoint에 422 HTTPValidationError | 자동 생성된 422 응답은 무시 옵션 |
| FastAPI | operationId `func_path_method` 패턴 너무 길음 | 정규화: path에서 추출 |
| springdoc | operationId 비결정적 `_1`, `_2` 접미사 | 있는 그대로 사용 (사용자 책임) |
| NestJS | operationId `Controller_method` 패턴 | 그대로 사용 |
| Go swag | `#/definitions/model.User` dot 포함 | dot 제거하여 정규화 |
| Go swag | Swagger 2.0 전용 구조 | 전체 2.0→3.0 변환 적용 |

## 인터페이스

```python
class SpecVersion(Enum):
    SWAGGER_2_0 = "2.0"
    OPENAPI_3_0 = "3.0"
    OPENAPI_3_1 = "3.1"

class NormalizedSpec:
    """정규화된 OpenAPI 3.0 호환 spec."""
    version: SpecVersion          # 원본 버전 (추적용)
    info: dict                    # API 메타데이터
    servers: list[dict]           # 서버 목록
    paths: dict                   # 정규화된 paths
    schemas: dict                 # 정규화된 components/schemas
    security_schemes: dict        # 정규화된 security
    raw: dict                     # 원본 보존

def normalize(spec: dict) -> NormalizedSpec:
    """Raw spec → 정규화된 내부 표현."""
    version = detect_version(spec)
    if version == SpecVersion.SWAGGER_2_0:
        spec = convert_swagger_2_to_3(spec)
    elif version == SpecVersion.OPENAPI_3_1:
        spec = downgrade_3_1_to_3_0(spec)
    return NormalizedSpec(...)
```

## 테스트 전략

```python
# 각 버전별 최소 spec으로 테스트
def test_swagger_2_petstore():       # Swagger 2.0 (Go swag 스타일)
def test_openapi_3_0_nestjs():       # OpenAPI 3.0 (NestJS 스타일)
def test_openapi_3_1_fastapi():      # OpenAPI 3.1 (FastAPI 스타일)
def test_nullable_normalization():    # 3가지 nullable 패턴
def test_ref_path_conversion():      # $ref 경로 변환
def test_body_to_request_body():     # Swagger body → requestBody
```
