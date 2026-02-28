# Phase 1: Ingest + Dependency + Ordering + Retrieval 개선

**상태**: ⬜ 진행 예정
**목표 기간**: 2주
**선행 조건**: Phase 0 ✅

## 완료 기준

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")

# CRUD dependency 감지
assert tg.graph.has_edge("addPet", "getPetById")

# PRECEDES 관계 (호출 순서)
assert tg.graph.has_edge("addPet", "uploadFile")  # 등록 후 업로드

# Retrieval
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
assert "addPet" in [t.name for t in tools]
assert "uploadFile" in [t.name for t in tools]

# SearchMode 지원
tools = tg.retrieve("register pet", top_k=5, mode="basic")  # LLM 없이 동작
```

## WBS 상세

### 1-1. 버그 수정

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-1a | tags 처리 TypeError 수정 | `retrieval/engine.py` | ⬜ |
| 1-1b | keyword scoring → BM25-style TF-IDF | `retrieval/engine.py` | ⬜ |

**세부**:
- `set.update(generator of lists)` → `for t in tags: tokens.update(tokenize(t))`
- token exact match → TF-IDF weighted scoring

---

### 1-2. Spec Normalization Layer

설계 문서: [design/spec-normalization.md](../design/spec-normalization.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-2a | 버전 감지 (swagger 2.0 / openapi 3.0 / 3.1) | `ingest/normalizer.py` | ⬜ |
| 1-2b | Swagger 2.0 → 3.x 구조 변환 | `ingest/normalizer.py` | ⬜ |
| 1-2c | nullable 정규화 (3패턴 통일) | `ingest/normalizer.py` | ⬜ |
| 1-2d | $ref 경로 정규화 | `ingest/normalizer.py` | ⬜ |

---

### 1-3. OpenAPI Ingest

설계 문서: [design/ingest-openapi.md](../design/ingest-openapi.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-3a | spec 로딩 (URL/파일, JSON/YAML) | `ingest/openapi.py` | ⬜ |
| 1-3b | $ref resolution (recursive) | `ingest/openapi.py` | ⬜ |
| 1-3c | operation → ToolSchema 변환 | `ingest/openapi.py` | ⬜ |
| 1-3d | 대형 request body: required만 노출 옵션 | `ingest/openapi.py` | ⬜ |
| 1-3e | deprecated endpoint 필터링 | `ingest/openapi.py` | ⬜ |

---

### 1-4. Dependency & Ordering Detection ← EXPANDED

설계 문서: [design/dependency-detection.md](../design/dependency-detection.md), [design/call-ordering.md](../design/call-ordering.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-4a | Layer 1: path hierarchy + CRUD pattern | `analyze/dependency.py` | ⬜ |
| 1-4b | Layer 1: $ref 스키마 공유 감지 | `analyze/dependency.py` | ⬜ |
| 1-4c | Layer 2: response→parameter name matching | `analyze/dependency.py` | ⬜ |
| 1-4d | naming convention 정규화 | `analyze/dependency.py` | ⬜ |
| 1-4e | confidence score + cycle detection | `analyze/dependency.py` | ⬜ |
| 1-4f | false positive 필터링 | `analyze/dependency.py` | ⬜ |
| **1-4g** | **PRECEDES RelationType 추가** | `ontology/schema.py` | ⬜ |
| **1-4h** | **CRUD workflow ordering** | `analyze/dependency.py` | ⬜ |
| **1-4i** | **State machine detection (enum status)** | `analyze/dependency.py` | ⬜ |

**1-4g 세부 (NEW)**:
- `RelationType` enum에 `PRECEDES = "precedes"` 추가
- PRECEDES vs REQUIRES 구분: 데이터 의존 vs 워크플로우 순서

**1-4h 세부 (NEW)**:
- 같은 리소스의 CRUD 순서: create(0) → read(1) → update(2) → delete(3)
- 순서 차이가 있는 CRUD 쌍에 PRECEDES 관계 생성

**1-4i 세부 (NEW)**:
- 스키마에서 `status`/`state` enum 필드 탐색
- enum 값 순서로 상태 전이 추론 (pending → confirmed → shipped)
- 상태 전이에 대응하는 API 쌍에 PRECEDES 관계

---

### 1-5. Auto-categorization

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-5a | tag 기반 카테고리 생성 | `ingest/openapi.py` | ⬜ |
| 1-5b | path prefix fallback (tag 없는 spec) | `ingest/openapi.py` | ⬜ |

---

### 1-6. Python callable ingest

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-6a | inspect.signature → ToolSchema | `ingest/functions.py` | ⬜ |
| 1-6b | docstring → description | `ingest/functions.py` | ⬜ |

---

### 1-7. Retrieval 개선 ← EXPANDED

설계 문서: [design/retrieval-engine.md](../design/retrieval-engine.md), [design/search-modes.md](../design/search-modes.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-7a | BM25-style keyword scoring | `retrieval/keyword.py` | ⬜ |
| 1-7b | RRF score fusion | `retrieval/engine.py` | ⬜ |
| 1-7c | tags 기반 scoring 통합 | `retrieval/engine.py` | ⬜ |
| **1-7d** | **SearchMode enum (BASIC/ENHANCED/FULL)** | `retrieval/engine.py` | ⬜ |
| **1-7e** | **Model-Driven API 스켈레톤** | `retrieval/model_driven.py` | ⬜ |

**1-7d 세부 (NEW)**:
- `SearchMode.BASIC` → Tier 0 (LLM 없이)
- `SearchMode.ENHANCED` → Tier 1 (query expansion)
- `SearchMode.FULL` → Tier 2 (intent decomposition)
- Phase 1에서는 enum + BASIC 구현, ENHANCED/FULL은 Phase 2

**1-7e 세부 (NEW)**:
- `ToolGraphSearchAPI` 클래스: `search_tools()`, `browse_categories()`, `get_related_tools()`
- Phase 1에서는 인터페이스 + 기본 구현
- Phase 3에서 LLM tool로 노출

---

### 1-8. OpenAPI 작성 가이드 문서 ← NEW

설계 문서: [design/openapi-guide.md](../design/openapi-guide.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-8a | OpenAPI best practice 가이드 작성 | `docs/design/openapi-guide.md` | ✅ |

**세부**:
- operationId 명명 규칙, tag 활용, RESTful path 계층
- $ref 스키마 공유, response ID 필드, enum 상태 정의
- 프레임워크별 팁 (FastAPI/Spring/NestJS)

---

### 1-9. Tests + Examples

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-9a | Petstore E2E 테스트 | `tests/test_ingest_openapi.py` | ⬜ |
| 1-9b | Swagger 2.0/3.0/3.1 각각 테스트 | `tests/test_normalizer.py` | ⬜ |
| 1-9c | Dependency + ordering detection 테스트 | `tests/test_dependency.py` | ⬜ |
| 1-9d | examples/swagger_to_agent.py | `examples/swagger_to_agent.py` | ⬜ |

## 의존 관계

```
1-1 (버그 수정)
  └→ 1-7 (Retrieval 개선) — 버그 수정 후 scoring 교체

1-2 (Spec Normalization)
  └→ 1-3 (OpenAPI Ingest) — 정규화 후 변환

1-3 (OpenAPI Ingest)
  ├→ 1-4 (Dependency + Ordering) — tool 있어야 관계/순서 분석
  └→ 1-5 (Auto-categorization) — tag/path 정보 필요

1-4g (PRECEDES type)
  └→ 1-4h, 1-4i — type 정의 후 감지 로직

1-6 (Python callable) — 독립, 병렬 가능
1-8 (OpenAPI 가이드) — 독립, 이미 완료 ✅

1-9 (Tests) — 모든 작업 완료 후
```
