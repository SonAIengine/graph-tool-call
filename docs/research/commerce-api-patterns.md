# Commerce API Patterns 리서치

## 동기

커머스 BO API는 1200+ endpoint로 구성되며 API 간 호출 순서가 존재.
주문 목록 조회 → 주문 상세 → 주문 취소 같은 워크플로우를 자동 감지하려면
커머스 도메인의 API 패턴을 이해해야 한다.

## 핵심 발견

### 1. Arazzo Specification (OpenAPI Initiative)

OpenAPI 공식 워크플로우 표준으로, API 호출 순서를 명시적으로 정의.

```yaml
arazzo: 1.0.0
info:
  title: Pet Purchase Workflow
workflows:
  - workflowId: pet-purchase
    steps:
      - stepId: login
        operationId: loginUser
        successCriteria:
          - condition: $statusCode == 200
      - stepId: find-pet
        operationId: findPetsByStatus
        dependsOn: login
        parameters:
          - name: status
            in: query
            value: available
      - stepId: place-order
        operationId: placeOrder
        dependsOn: find-pet
```

**활용**: Arazzo spec이 제공되면 완벽한 PRECEDES 관계 추출 가능.

### 2. commercetools State Machine Model

commercetools는 8개 StateType으로 리소스 라이프사이클 관리:

| StateType | 리소스 | 전형적 전이 |
|-----------|--------|------------|
| OrderState | 주문 | Open → Confirmed → Complete / Cancelled |
| PaymentState | 결제 | BalanceDue → Paid → CreditOwed |
| LineItemState | 주문 항목 | Initial → Shipped → Returned |
| ProductState | 상품 | Draft → Published |
| ReviewState | 리뷰 | Pending → Approved / Rejected |
| QuoteRequestState | 견적 | Submitted → Accepted / Declined |
| QuoteState | 견적 | Pending → Accepted |
| StagedQuoteState | 단계별 견적 | InProgress → Sent |

각 상태에 `transitions` 필드로 허용 전이를 제한:

```json
{
  "key": "order-confirmed",
  "type": "OrderState",
  "transitions": [
    {"typeId": "state", "id": "order-complete"},
    {"typeId": "state", "id": "order-cancelled"}
  ]
}
```

**활용**: 스키마의 enum + status 필드에서 상태 머신을 추론하여 PRECEDES 감지.

### 3. RESTler / Apigraph — API 의존성 그래프

**RESTler** (Microsoft, ICSE 2019):
- Producer-consumer inference로 API 간 데이터 의존 자동 감지
- 3-tier matching: annotation → exact name → fuzzy name
- Precision ~75% (Layer 2), Recall ~85%

**Apigraph**:
- `x-apigraph-backlinks` 커스텀 확장으로 역방향 의존 명시
- 예: DELETE /pets/{petId}의 backlink → POST /pets (petId를 생성하는 API)

### 4. 커머스 도메인 워크플로우 패턴

#### 주문 라이프사이클

```
[상품 검색] → [장바구니] → [주문 생성] → [결제] → [배송] → [완료]
                                        ↘ [취소] → [환불]
                                                  ↘ [반품] → [환불]
```

#### 결제 워크플로우 (Stripe 패턴)

```
PaymentIntent 생성
  → confirm (인증)
    → capture (청구)   or   → cancel (취소)
  → refund (환불, 별도 리소스)
```

#### 상품 관리

```
상품 생성 → 이미지 업로드 → 재고 설정 → 카테고리 할당 → 게시
                                                        ↓
                                                    가격 변경
                                                        ↓
                                                    비게시 / 삭제
```

## 규모 데이터

| 커머스 플랫폼 | 예상 Endpoint 수 | 리소스 수 |
|--------------|-----------------|----------|
| Shopify Admin API | ~400 | ~60 |
| commercetools | ~300+ | ~40+ |
| Stripe | 587 | ~100+ |
| WooCommerce REST | ~100 | ~20 |
| 일반 커머스 BO | 500~1500 | 50~200 |

## 설계 반영

1. **PRECEDES RelationType 추가** — 호출 순서 관계
2. **State machine detection** — enum status 필드 자동 분석
3. **Arazzo spec 파서** (Phase 2) — 워크플로우 명세서 직접 파싱
4. **커머스 도메인 프리셋** (Phase 3) — 주문/결제/배송 패턴 템플릿
5. **1000+ endpoint 최적화** — incremental 파싱, batch 분석

## 참고

- [Arazzo Specification](https://spec.openapis.org/arazzo/latest.html)
- [RESTler: Stateful REST API Fuzzing](https://www.microsoft.com/en-us/research/publication/restler-stateful-rest-api-fuzzing/) (ICSE 2019)
- [commercetools State Machine](https://docs.commercetools.com/api/projects/states)
- [Apigraph](https://github.com/apigraph/apigraph)
