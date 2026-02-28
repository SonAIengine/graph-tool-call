# Dependency Detection — 설계 문서

**WBS**: 1-4
**파일**: `analyze/dependency.py`
**선행**: 1-3 (OpenAPI Ingest)
**학술 근거**: RESTler (ICSE 2019), RestTestGen (ICST 2020)

## 관계 타입

```python
class RelationType(str, Enum):
    REQUIRES = "requires"               # A 없으면 B 호출 불가 (데이터 의존)
    COMPLEMENTARY = "complementary"     # A와 B를 함께 쓰면 유용
    SIMILAR_TO = "similar_to"           # A와 B가 유사 기능
    CONFLICTS_WITH = "conflicts_with"   # A와 B가 충돌
    BELONGS_TO = "belongs_to"           # 카테고리 소속
    PRECEDES = "precedes"               # A → B 호출 순서 (워크플로우) ← NEW
```

**REQUIRES vs PRECEDES**:
- REQUIRES: `addPet`의 response.id가 `getPetById`의 parameter.petId에 필요 (데이터)
- PRECEDES: `listOrders`를 먼저 호출해야 `cancelOrder`가 의미있음 (워크플로우)

상세: [design/call-ordering.md](call-ordering.md)

## 3-Layer 알고리즘

```
Layer 1: Structural (Precision ~95%, Recall ~60%)
  ├─ path hierarchy: /users/{id}/orders → parent-child
  ├─ CRUD pattern: same base path + different HTTP method
  ├─ $ref schema 공유
  ├─ CRUD workflow ordering → PRECEDES ← NEW
  └─ State machine detection (enum status) → PRECEDES ← NEW

Layer 2: Name-based (Precision ~75%, Recall ~85%)
  ├─ response field → parameter name matching
  ├─ naming convention 정규화 (camelCase ↔ snake_case ↔ kebab-case)
  ├─ container + field concatenation (user.id → userId)
  └─ action prefix ordering (initiate → verify → complete) ← NEW

Layer 3: Semantic (Phase 2)
  ├─ embedding similarity
  ├─ LLM reasoning
  └─ Arazzo Specification (워크플로우 명세) ← NEW

Layer 1+2 결합: Precision ~80%, Recall ~85%
```

## Layer 1: Structural

### 1a. Path Hierarchy

```
/users              POST  → createUser
/users/{userId}     GET   → getUser
/users/{userId}/orders  GET → getUserOrders

관계:
  createUser → getUser         (REQUIRES, 0.95)
  createUser → getUserOrders   (REQUIRES, 0.95)
```

### 1b. CRUD Pattern

```
같은 base path의 HTTP method 조합:
  POST   (create) → GET/{id} (read)    = REQUIRES (0.95)
  POST   (create) → PUT/{id} (update)  = COMPLEMENTARY (0.9)
  GET/{id} (read) ↔ GET      (list)    = SIMILAR_TO (0.85)
  PUT    (update) ↔ DELETE   (delete)  = CONFLICTS_WITH (0.8)
```

### 1c. $ref Schema 공유

```
addPet:     requestBody → $ref: Pet
getPetById: response    → $ref: Pet

같은 Pet 스키마 참조 → COMPLEMENTARY (0.85)
```

## Layer 2: Name-based

### 2a. Response → Parameter Matching

```
addPet response:   { "id": 123, "name": "doggy" }
getPetById param:  petId (in: path)

매칭: response.id → param.petId (suffix "id" 일치)
결과: addPet → getPetById (REQUIRES, 0.75)
```

### 2b. Naming Convention 정규화

```python
def normalize_name(name: str) -> list[str]:
    """모든 naming convention → 토큰 리스트."""
    # "userId"    → ["user", "id"]
    # "user_id"   → ["user", "id"]
    # "user-id"   → ["user", "id"]
    # "UserID"    → ["user", "id"]
```

## False Positive 필터링

| 패턴 | 예시 | 대응 |
|------|------|------|
| Generic field name | `id`, `name`, `type` | container name 포함 매칭 |
| Type mismatch | string `id` → integer `petId` | type 일치 검증 |
| Circular dependency | A → B → A | DFS cycle detection |
| Same-endpoint self-ref | GET response.id → GET query.id | self-reference 제외 |

## Layer 1 확장: CRUD Workflow Ordering (NEW)

```python
CRUD_WORKFLOW = {
    "create": 0,    # POST
    "read": 1,      # GET /{id}
    "list": 1,      # GET /
    "update": 2,    # PUT/PATCH
    "delete": 3,    # DELETE
}
# create(0) PRECEDES read(1) PRECEDES update(2) PRECEDES delete(3)
```

## Layer 1 확장: State Machine Detection (NEW)

```python
# 스키마에서 status/state enum 필드를 찾아 상태 전이 추론
# Order.status: ["pending", "confirmed", "shipped", "cancelled"]
# → pending → confirmed: createOrder PRECEDES confirmOrder
# → confirmed → shipped: confirmOrder PRECEDES shipOrder
```

상세 알고리즘: [design/call-ordering.md](call-ordering.md)

## 출력

```python
@dataclass
class DetectedRelation:
    source: str              # tool name
    target: str              # tool name
    relation_type: RelationType  # REQUIRES, PRECEDES, COMPLEMENTARY, etc.
    confidence: float        # 0.0 ~ 1.0
    evidence: str            # 근거 설명
    layer: int               # 1 or 2

def detect_dependencies(
    tools: list[ToolSchema],
    spec: NormalizedSpec,
    *,
    min_confidence: float = 0.7,
) -> list[DetectedRelation]:
```
