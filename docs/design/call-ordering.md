# API Call Ordering & Sequencing — 설계 문서

**WBS**: 1-4g, 1-4h (Phase 1 확장)
**파일**: `analyze/dependency.py`, `ontology/schema.py`
**학술 근거**: RESTler (ICSE 2019), Arazzo Specification (OpenAPI Initiative)

## 동기

커머스 BO API 같은 대형 시스템에서는 API 간 **호출 순서**가 존재한다:

```
주문 목록 조회 → 주문 상세 조회 → 주문 취소 요청
(listOrders)    (getOrder)       (cancelOrder)

주문 목록을 조회하지 않으면 주문 취소가 불가능.
이 순서 관계를 자동으로 감지해야 한다.
```

## 새 RelationType: PRECEDES

기존 관계 타입에 추가:

```python
class RelationType(str, Enum):
    REQUIRES = "requires"               # A 없으면 B 호출 불가
    COMPLEMENTARY = "complementary"     # A와 B를 함께 쓰면 유용
    SIMILAR_TO = "similar_to"           # A와 B가 유사 기능
    CONFLICTS_WITH = "conflicts_with"   # A와 B가 충돌
    BELONGS_TO = "belongs_to"           # 카테고리 소속
    PRECEDES = "precedes"               # A → B 호출 순서 (NEW)
```

`PRECEDES`는 `REQUIRES`와 다르다:
- **REQUIRES**: A의 출력이 B의 입력에 필요 (데이터 의존)
- **PRECEDES**: A를 먼저 호출해야 B가 의미있음 (워크플로우 순서)

예시:
- `listOrders` PRECEDES `cancelOrder` — 목록에서 선택해야 취소 가능
- `createPayment` PRECEDES `capturePayment` — 결제 생성 후 캡처
- `addToCart` PRECEDES `checkout` — 장바구니 담은 후 결제

## 감지 알고리즘

### Layer 1 확장: State Machine Detection

API 스키마의 enum 필드에서 상태 전이를 추론:

```python
def detect_state_transitions(tools, spec):
    """enum 필드 + status/state 필드명으로 상태 머신 추론."""
    relations = []

    # 1. status/state enum 필드 찾기
    state_fields = find_state_fields(spec)
    # e.g., Order.status: ["pending", "confirmed", "shipped", "cancelled"]

    # 2. 각 tool이 어떤 상태 전이를 일으키는지 추론
    for tool in tools:
        method = tool.metadata.get("method", "").upper()
        # POST → 초기 상태 생성
        # PUT/PATCH → 상태 변경
        # DELETE → 최종 상태

    # 3. 상태 순서로 PRECEDES 관계 생성
    # pending → confirmed: createOrder PRECEDES confirmOrder
    # confirmed → shipped: confirmOrder PRECEDES shipOrder

    return relations
```

### Layer 1 확장: CRUD Workflow Pattern

기존 CRUD 감지를 확장하여 호출 순서 추론:

```python
CRUD_WORKFLOW = {
    # 표준 CRUD 순서
    "create": 0,    # POST
    "read": 1,      # GET /{id}
    "list": 1,      # GET /
    "update": 2,    # PUT/PATCH
    "delete": 3,    # DELETE
}

# 같은 리소스의 CRUD는 순서 관계
# create(0) PRECEDES read(1) PRECEDES update(2) PRECEDES delete(3)
```

### Layer 2 확장: Naming Convention

```
# 접두사/접미사 패턴으로 순서 감지
"initiate" / "start" / "begin" → 선행 단계
"complete" / "finish" / "finalize" → 후행 단계
"verify" / "validate" / "confirm" → 중간 단계

# 예: initiatePayment → verifyPayment → completePayment
```

### Layer 3 (Phase 2): Arazzo 기반

[Arazzo Specification](https://spec.openapis.org/arazzo/latest.html) — OpenAPI 공식 워크플로우 표준:

```yaml
# arazzo.yaml 예시
workflows:
  - workflowId: pet-purchase
    steps:
      - stepId: login
        operationId: loginUser
      - stepId: find-pet
        operationId: findPetsByStatus
        dependsOn: login
      - stepId: place-order
        operationId: placeOrder
        dependsOn: find-pet
```

Arazzo spec이 있으면 완벽한 순서 관계를 추출할 수 있다.
없으면 Layer 1+2의 휴리스틱으로 추론.

## 커머스 도메인 특화 패턴

### 주문 워크플로우

```
[장바구니] → [주문 생성] → [결제] → [배송] → [완료/취소/반품]

addToCart
  → PRECEDES → createOrder
    → PRECEDES → initiatePayment
      → PRECEDES → confirmPayment
        → PRECEDES → createShipment
          → PRECEDES → confirmDelivery
```

### 결제 워크플로우 (Stripe 패턴)

```
createPaymentIntent → confirmPaymentIntent → capturePaymentIntent
                    ↘ cancelPaymentIntent (분기)
```

### 상태 기반 감지 (commercetools 참고)

```
StateType별 전이:
  OrderState:  Open → Confirmed → Complete / Cancelled
  PaymentState: BalanceDue → Paid → CreditOwed
  ShipmentState: Shipped → Delivered / Returned

각 상태 전이에 대응하는 API가 PRECEDES 관계
```

## False Positive 대응

| 패턴 | 예시 | 대응 |
|------|------|------|
| 병렬 가능 API를 순서로 잘못 감지 | updateAddress, updatePhone | 같은 단계(동일 CRUD level)면 PRECEDES 아님 |
| 조건부 순서 | cancelOrder는 shipped 상태에서만 | confidence 낮게 (0.6), 조건 메타데이터 기록 |
| 순환 워크플로우 | refund → re-order → refund | DFS cycle detection으로 순환 제거 |

## 출력 예시

```python
DetectedRelation(
    source="listOrders",
    target="cancelOrder",
    relation_type=RelationType.PRECEDES,
    confidence=0.85,
    evidence="CRUD workflow: list(1) precedes delete(3) on same resource 'orders'",
    layer=1,
)
```

## 구현 범위

| Phase | 작업 | 설명 |
|-------|------|------|
| **1** | CRUD workflow ordering | CRUD 패턴에서 순서 추론 |
| **1** | State field detection | enum status 필드에서 상태 머신 |
| **1** | PRECEDES RelationType 추가 | 온톨로지 스키마 확장 |
| **2** | Naming convention ordering | 접두사/접미사 패턴 |
| **2** | Arazzo spec 지원 | 워크플로우 명세서 파싱 |
| **3** | 커머스 도메인 프리셋 | 주문/결제/배송 패턴 템플릿 |
