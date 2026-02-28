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
1. operationId 있으면 → 그대로 사용
2. 없으면 → "{method}_{path_slug}" 생성
   예: GET /pets/{petId} → "get_pets_petId"
3. 충돌 시 → 숫자 접미사 "_2", "_3"
```

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
