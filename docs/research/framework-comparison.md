# 프레임워크별 OpenAPI Spec 비교

## 버전별 구조 차이

| | Swagger 2.0 | OpenAPI 3.0 | OpenAPI 3.1 |
|--|------------|------------|------------|
| 버전 필드 | `"swagger": "2.0"` | `"openapi": "3.0.x"` | `"openapi": "3.1.x"` |
| 스키마 위치 | `definitions` | `components/schemas` | `components/schemas` |
| $ref 경로 | `#/definitions/User` | `#/components/schemas/User` | `#/components/schemas/User` |
| nullable | `x-nullable: true` | `nullable: true` | `anyOf: [{type:"string"},{type:"null"}]` |
| 서버 정보 | `host` + `basePath` | `servers: [...]` | `servers: [...]` |
| Security | `securityDefinitions` | `components/securitySchemes` | `components/securitySchemes` |
| 파라미터 | `type` 직접 명시 | `schema: {type}` | `schema: {type}` |

## 프레임워크별 기본 생성 버전

| 프레임워크 | 언어 | 기본 버전 | operationId 패턴 |
|-----------|------|----------|------------------|
| FastAPI | Python | **3.1.0** | `read_item_items__item_id__get` |
| NestJS | Node.js | **3.0.0** | `PetsController_create` |
| Express + swagger-jsdoc | Node.js | **수동 지정** | 수동 |
| springdoc v2 | Java | **3.0.1** | `getBookById` (메서드명) |
| springdoc v3 | Java | **3.1.0** | `getBookById` |
| springfox (폐기) | Java | **2.0** | 자동 생성 |
| swaggo/swag | Go | **2.0** | 주석/함수명 |

## 프레임워크별 고유 특징

### FastAPI (3.1)
- 모든 endpoint에 `422 HTTPValidationError` 자동 삽입
- Optional → `anyOf: [{type:"string"},{type:"null"}]` (복잡)
- operationId: `{func}_{path}_{method}` (너무 길어짐)
- Pydantic 모델 → title 필드 자동 생성

### NestJS (3.0)
- `servers: []` 빈 배열, description `""` 빈 문자열
- operationId: `{Controller}_{method}`
- `@ApiProperty()` 누락 시 필드가 schema에서 사라짐 (silent)

### springdoc (3.0/3.1)
- JSR-303 (`@NotNull`, `@Min`) → schema 제약조건 자동 변환
- operationId 충돌 시 `_1`, `_2` 접미사 (**비결정적**)
- Java 상속 → `allOf` 패턴
- `discriminator` + `oneOf` (다형성)

### Go swag (2.0)
- `#/definitions/model.User` — **패키지명 포함, dot 포함**
- Swagger 2.0 전용 구조 (definitions, host+basePath)
- OpenAPI 3.0 기능 표현 불가 (oneOf, anyOf)

## 파싱 시 핵심 주의점

1. **버전 감지**: `swagger` 키 → 2.0, `openapi` 키 → 3.x
2. **nullable 3패턴**: `anyOf+null`, `nullable:true`, `x-nullable:true` 모두 처리
3. **$ref 경로**: Go의 `#/definitions/pkg.Type` dot 처리
4. **body → requestBody**: Swagger 2.0의 `in:body` → 3.0의 `requestBody` 변환
5. **422 자동 응답**: FastAPI의 HTTPValidationError 무시 옵션 필요
