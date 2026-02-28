# OpenAPI Spec 작성 가이드 — Tool Ontology 최적화

**목적**: OpenAPI/Swagger spec을 작성할 때 graph-tool-call이 더 정확한 tool graph를 생성하도록 하는 best practice.

> 이 가이드를 따르지 않아도 graph-tool-call은 동작합니다.
> 하지만 가이드를 따르면 관계 감지 정확도가 크게 향상됩니다.

## 1. operationId 명명 규칙

### 권장

```yaml
# 패턴: {action}{Resource}
paths:
  /users:
    post:
      operationId: createUser    # ✅ 동사 + 명사
    get:
      operationId: listUsers     # ✅ list는 복수형
  /users/{userId}:
    get:
      operationId: getUser       # ✅ get은 단수형
    put:
      operationId: updateUser
    delete:
      operationId: deleteUser
```

### 비권장

```yaml
# ❌ 프레임워크가 자동 생성한 이름
operationId: UsersController_findAll      # NestJS 스타일
operationId: users_api_get_user_by_id     # 너무 길고 구조 불명확
operationId: endpoint_23                   # 의미 없음
```

**효과**: CRUD 패턴 감지 정확도 95% → operationId가 없으면 path에서 추론 (정확도 75%)

## 2. Tag 활용

```yaml
tags:
  - name: pets
    description: Pet management operations
  - name: orders
    description: Order lifecycle management

paths:
  /pets:
    post:
      tags: [pets]              # ✅ tag 필수
      operationId: addPet
  /orders:
    post:
      tags: [orders]            # ✅ 같은 도메인은 같은 tag
      operationId: createOrder
```

**효과**: tag → 자동 카테고리 생성. tag 없으면 path prefix로 fallback (정확도 낮음)

> ⚠️ Stripe API는 tag가 전혀 없어서 587개 endpoint를 path prefix로만 분류해야 합니다.

## 3. 일관된 리소스 구조

### 권장: RESTful 계층

```yaml
# 리소스 계층 = path 계층
/users                        # 컬렉션
/users/{userId}               # 단일 리소스
/users/{userId}/orders        # 하위 리소스 (parent-child 관계 자동 감지)
/users/{userId}/orders/{orderId}
/users/{userId}/orders/{orderId}/items
```

### 비권장

```yaml
# ❌ flat한 path는 관계 감지 불가
/getUser
/getUserOrders
/createOrder
/cancelUserOrder
```

**효과**: path hierarchy → REQUIRES 관계 자동 감지 (confidence 0.95)

## 4. $ref로 스키마 공유 명시

```yaml
components:
  schemas:
    Pet:                        # ✅ 공유 스키마 정의
      type: object
      properties:
        id:
          type: integer
        name:
          type: string

paths:
  /pets:
    post:
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Pet'    # ✅ $ref 사용
  /pets/{petId}:
    get:
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'  # ✅ 같은 $ref → COMPLEMENTARY 감지
```

**효과**: 같은 `$ref` 참조 → COMPLEMENTARY 관계 자동 감지 (confidence 0.85)

## 5. Response 스키마에 ID 필드 명시

```yaml
# ✅ response에 id 필드가 있으면 → 다른 endpoint의 parameter와 매칭
/pets:
  post:
    responses:
      '201':
        content:
          application/json:
            schema:
              type: object
              properties:
                id:                    # ✅ 이 필드가
                  type: integer
                  description: Pet ID

/pets/{petId}:                         # ✅ 이 parameter와 매칭됨
  get:
    parameters:
      - name: petId                    # response.id → param.petId (REQUIRES 감지)
        in: path
        schema:
          type: integer
```

**효과**: producer-consumer 관계 자동 감지 (RESTler 알고리즘)

## 6. Enum으로 상태 정의

```yaml
components:
  schemas:
    Order:
      properties:
        status:
          type: string
          enum:                        # ✅ enum으로 상태 정의
            - pending
            - confirmed
            - shipped
            - delivered
            - cancelled
          description: "Order lifecycle status"
```

**효과**: enum 상태 → PRECEDES (호출 순서) 관계 자동 추론

```
pending → confirmed: createOrder PRECEDES confirmOrder
confirmed → shipped: confirmOrder PRECEDES shipOrder
```

## 7. Deprecated 표시

```yaml
/pets/findByTags:
  get:
    deprecated: true                   # ✅ deprecated 표시
    description: "Use findPetsByStatus instead"
```

**효과**: deprecated endpoint는 tool graph에서 자동 제외 (옵션)

## 8. Description 충실하게

```yaml
/orders/{orderId}/cancel:
  post:
    summary: "Cancel an order"         # ✅ 짧은 요약
    description: |                     # ✅ 상세 설명
      Cancels a pending or confirmed order.
      Cannot cancel shipped orders.
      Requires the order to exist (call getOrder first).
    operationId: cancelOrder
```

**효과**: description → BM25 keyword matching + embedding similarity 정확도 향상

## 9. Arazzo Workflow (선택)

API 간 호출 순서가 중요하면 Arazzo spec 추가:

```yaml
# arazzo.yaml
arazzo: 1.0.0
info:
  title: Order Workflow
workflows:
  - workflowId: order-cancel
    steps:
      - stepId: list
        operationId: listOrders
      - stepId: get
        operationId: getOrder
        dependsOn: list
      - stepId: cancel
        operationId: cancelOrder
        dependsOn: get
```

**효과**: 완벽한 호출 순서 관계 추출 (confidence 1.0)

## 체크리스트

| # | 항목 | 영향 | 필수 |
|---|------|------|------|
| 1 | operationId에 `{action}{Resource}` 패턴 | CRUD 감지 | ★★★ |
| 2 | 모든 operation에 tag | 카테고리 | ★★★ |
| 3 | RESTful path 계층 | 부모-자식 관계 | ★★☆ |
| 4 | $ref로 스키마 공유 | COMPLEMENTARY | ★★☆ |
| 5 | Response에 ID 필드 | REQUIRES | ★★☆ |
| 6 | Enum으로 상태 정의 | PRECEDES | ★★☆ |
| 7 | Deprecated 표시 | 필터링 | ★☆☆ |
| 8 | Description 충실히 | 검색 품질 | ★★☆ |
| 9 | Arazzo workflow | 호출 순서 | ★☆☆ |

## 프레임워크별 팁

### FastAPI

```python
@app.post("/users", tags=["users"], operation_id="createUser")
async def create_user(user: UserCreate) -> User:
    """Create a new user account.

    Returns the created user with generated ID.
    """
```

### Spring (springdoc)

```java
@Operation(
    operationId = "createUser",
    summary = "Create user",
    tags = {"users"}
)
@PostMapping("/users")
public User createUser(@RequestBody UserCreate user) { ... }
```

### NestJS (Swagger)

```typescript
@ApiTags('users')
@ApiOperation({ operationId: 'createUser', summary: 'Create user' })
@Post('/users')
createUser(@Body() user: CreateUserDto): User { ... }
```
