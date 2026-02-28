# Phase 1: Ingest + Dependency + Retrieval 개선

**상태**: ⬜ 진행 예정
**목표 기간**: 2주
**선행 조건**: Phase 0 ✅

## 완료 기준

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
assert tg.graph.has_edge("addPet", "getPetById")  # CRUD dependency
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
assert "addPet" in [t.name for t in tools]
assert "uploadFile" in [t.name for t in tools]
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

### 1-2. Spec Normalization Layer ← NEW

설계 문서: [design/spec-normalization.md](../design/spec-normalization.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-2a | 버전 감지 (swagger 2.0 / openapi 3.0 / 3.1) | `ingest/normalizer.py` | ⬜ |
| 1-2b | Swagger 2.0 → 3.x 구조 변환 | `ingest/normalizer.py` | ⬜ |
| 1-2c | nullable 정규화 (3패턴 통일) | `ingest/normalizer.py` | ⬜ |
| 1-2d | $ref 경로 정규화 | `ingest/normalizer.py` | ⬜ |

**세부**:
- 입력: raw spec dict (JSON/YAML 파싱 후)
- 출력: OpenAPI 3.0 정규화된 dict
- Swagger 2.0: `definitions` → `components/schemas`, `host`+`basePath` → `servers`
- nullable: `anyOf+null` / `nullable:true` / `x-nullable:true` → 통일 표현
- $ref: `#/definitions/pkg.Type` → `#/components/schemas/PkgType`

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

**세부**:
- `tg.ingest_openapi(source)` → source는 URL string, file path, 또는 dict
- operationId 있으면 tool name으로 사용, 없으면 `{method}_{path_slug}` 생성
- parameters: path + query + header + requestBody 통합
- response schema를 metadata에 저장 (dependency detection용)

---

### 1-4. Dependency Detection

설계 문서: [design/dependency-detection.md](../design/dependency-detection.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-4a | Layer 1: path hierarchy + CRUD pattern | `analyze/dependency.py` | ⬜ |
| 1-4b | Layer 1: $ref 스키마 공유 감지 | `analyze/dependency.py` | ⬜ |
| 1-4c | Layer 2: response→parameter name matching | `analyze/dependency.py` | ⬜ |
| 1-4d | naming convention 정규화 | `analyze/dependency.py` | ⬜ |
| 1-4e | confidence score + cycle detection | `analyze/dependency.py` | ⬜ |
| 1-4f | false positive 필터링 | `analyze/dependency.py` | ⬜ |

---

### 1-5. Auto-categorization

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-5a | tag 기반 카테고리 생성 | `ingest/openapi.py` | ⬜ |
| 1-5b | path prefix fallback (tag 없는 spec) | `ingest/openapi.py` | ⬜ |

**세부**:
- tag 있으면: tag → category name
- tag 없으면: path 첫 segment → category (예: `/pets/...` → `pets`)
- Stripe처럼 tag 전혀 없는 spec 대응 필수

---

### 1-6. Python callable ingest

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-6a | inspect.signature → ToolSchema | `ingest/functions.py` | ⬜ |
| 1-6b | docstring → description | `ingest/functions.py` | ⬜ |

---

### 1-7. Retrieval 개선

설계 문서: [design/retrieval-engine.md](../design/retrieval-engine.md)

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-7a | BM25-style keyword scoring | `retrieval/keyword.py` | ⬜ |
| 1-7b | RRF score fusion | `retrieval/engine.py` | ⬜ |
| 1-7c | tags 기반 scoring 통합 | `retrieval/engine.py` | ⬜ |

---

### 1-8. Tests + Examples

| ID | 작업 | 파일 | 상태 |
|----|------|------|------|
| 1-8a | Petstore E2E 테스트 | `tests/test_ingest_openapi.py` | ⬜ |
| 1-8b | Swagger 2.0/3.0/3.1 각각 테스트 | `tests/test_normalizer.py` | ⬜ |
| 1-8c | Dependency detection 테스트 | `tests/test_dependency.py` | ⬜ |
| 1-8d | examples/swagger_to_agent.py | `examples/swagger_to_agent.py` | ⬜ |

## 의존 관계

```
1-1 (버그 수정)
  └→ 1-7 (Retrieval 개선) — 버그 수정 후 scoring 교체

1-2 (Spec Normalization)
  └→ 1-3 (OpenAPI Ingest) — 정규화 후 변환

1-3 (OpenAPI Ingest)
  ├→ 1-4 (Dependency Detection) — tool 있어야 관계 분석
  └→ 1-5 (Auto-categorization) — tag/path 정보 필요

1-6 (Python callable) — 독립, 병렬 가능

1-8 (Tests) — 모든 작업 완료 후
```
