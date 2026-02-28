# Data Model

## ToolSchema

tool의 통합 내부 표현. 모든 포맷(OpenAI, Anthropic, LangChain, OpenAPI)이 이 모델로 정규화됨.

```python
class ToolSchema(BaseModel):
    name: str                              # 고유 식별자
    description: str = ""                  # 자연어 설명
    parameters: list[ToolParameter] = []   # 입력 파라미터
    tags: list[str] = []                   # 분류 태그
    domain: str | None = None              # 소속 도메인
    metadata: dict[str, Any] = {}          # 확장 메타데이터

class ToolParameter(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[Any] | None = None
```

### metadata 확장 (OpenAPI ingest 시)

```python
metadata = {
    "source": "openapi",
    "spec_version": "3.1.0",           # 원본 spec 버전
    "path": "/pets/{petId}",           # API path
    "method": "GET",                   # HTTP method
    "operation_id": "getPetById",      # 원본 operationId
    "tags": ["pet"],                   # 원본 tags
    "deprecated": False,
    "security": ["bearerAuth"],
    "response_schema": {...},          # 응답 스키마 (dependency detection용)
    "request_content_type": "application/json",
}
```

## RelationType

tool 간 관계 6종:

| Type | Weight | 의미 | 예시 |
|------|--------|------|------|
| `REQUIRES` | 1.0 | A의 출력이 B의 입력에 필요 (데이터 의존) | POST /pet → GET /pet/{id} |
| `PRECEDES` | 0.9 | A → B 호출 순서 (워크플로우 순서) | listOrders → cancelOrder |
| `COMPLEMENTARY` | 0.7 | 함께 쓰면 효과적 | read_file ↔ write_file |
| `SIMILAR_TO` | 0.8 | 비슷한 기능 | GET /pet/{id} ↔ GET /pets |
| `CONFLICTS_WITH` | 0.2 | 동시 실행 시 문제 | update_pet ↔ delete_pet |
| `BELONGS_TO` | 0.5 | 카테고리 소속 | read_file → file_operations |

> **REQUIRES vs PRECEDES**: REQUIRES는 데이터 의존 (response → parameter),
> PRECEDES는 워크플로우 순서 (목록 조회 → 취소). 상세: [design/call-ordering.md](../design/call-ordering.md)

## NodeType

그래프 노드 3종:

| Type | 설명 | 예시 |
|------|------|------|
| `TOOL` | 실제 tool | read_file, addPet |
| `CATEGORY` | tool 그룹 | file_operations, pet |
| `DOMAIN` | 상위 도메인 | io, data |

## 그래프 구조

```
Domain: io ──BELONGS_TO──→ Category: file_ops
                                │
                     ┌──────────┼──────────┐
                BELONGS_TO  BELONGS_TO  BELONGS_TO
                     │          │          │
                  read_file  write_file  delete_file
                     │          │
                COMPLEMENTARY   SIMILAR_TO
                     └──────────┘
```
