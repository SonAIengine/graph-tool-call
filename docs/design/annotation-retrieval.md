# MCP Annotation-Aware Retrieval — 설계 문서

**WBS**: 2.5
**파일**: `core/tool.py`, `ingest/mcp.py`, `ingest/openapi.py`, `retrieval/intent.py`, `retrieval/annotation_scorer.py`, `retrieval/engine.py`

## 동기

기존 retrieval은 BM25(keyword) + Graph(BFS) + Embedding의 3-source wRRF fusion만 사용. MCP spec의 tool annotation(`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)은 도구의 **행동적 의미(behavioral semantics)**를 인코딩하며, 이를 retrieval signal로 활용하면 query intent와 도구 행동이 일치하는 도구를 우선순위화할 수 있음.

**학술적 novelty**: 기존 연구는 textual similarity + structural dependency만 사용. annotation을 retrieval signal로 활용하는 연구는 전무.

## 파이프라인

```
Query: "사용자 삭제"
  │
  ├─ [1] BM25 keyword score
  ├─ [2] Graph expansion score
  ├─ [3] Embedding score (optional)
  │
  ├─ [4] Intent Classification (NEW)
  │      classify_intent("사용자 삭제")
  │      → QueryIntent(read=0.0, write=0.0, delete=1.0)
  │
  ├─ [5] Annotation Scoring (NEW)
  │      delete_user (destructive=True)  → score=0.85
  │      get_user    (readOnly=True)     → score=0.0
  │      create_user (readOnly=False)    → score=0.35
  │
  └─ [6] 4-source wRRF Fusion
         sources = [BM25, Graph, Embedding, Annotation(w=0.2)]
         → delete_user 상위 랭크
```

## Intent Classifier

**파일**: `retrieval/intent.py`

Zero-LLM 키워드 기반 분류. 한/영 키워드 사전 매칭.

```python
@dataclass
class QueryIntent:
    read_intent: float = 0.0    # 0.0~1.0
    write_intent: float = 0.0
    delete_intent: float = 0.0
```

### 키워드 사전

| Intent | 영어 | 한국어 |
|--------|------|--------|
| read | get, list, show, read, fetch, search, find, view, query, lookup, check | 조회, 목록, 보기, 검색, 확인, 찾기 |
| write | create, add, update, modify, edit, set, put, post, write, save | 생성, 추가, 수정, 변경, 등록, 저장 |
| delete | delete, remove, destroy, drop, purge, erase, cancel, terminate | 삭제, 제거, 취소, 해제, 폐기 |

### 정규화

```
total = read_hits + write_hits + delete_hits
read_intent = read_hits / total  (total > 0)
```

키워드가 없으면 neutral intent → annotation scoring 건너뜀 (noise 방지).

## Annotation Scorer

**파일**: `retrieval/annotation_scorer.py`

Intent와 annotation의 alignment score 계산.

### 스코어링 규칙

| Intent | Annotation | Score | 해석 |
|--------|-----------|-------|------|
| read=1.0 | readOnly=True | **1.0** | perfect match |
| read=1.0 | readOnly=False | 0.3 | mild mismatch |
| write=1.0 | readOnly=True | **0.0** | hard mismatch |
| write=1.0 | readOnly=False | 1.0 | match |
| delete=1.0 | destructive=True | **1.0** | match |
| delete=1.0 | destructive=False | 0.1 | mismatch |
| delete=1.0 | readOnly=True | **0.0** | hard mismatch |
| neutral | any | 0.5 | neutral (건너뜀) |
| any | None | 0.5 | neutral |

### Noise 방지

- Neutral intent → `compute_annotation_scores()` 빈 dict 반환
- Neutral score (0.5) → scores dict에서 제외
- Annotation이 None인 도구 → neutral 처리

## wRRF 통합

**파일**: `retrieval/engine.py`

```python
score_sources = [
    (keyword_scores, 1.0),       # BM25
    (graph_scores, 1.0),         # Graph expansion
    (embedding_scores, 1.0),     # Embedding (optional)
    (annotation_scores, 0.2),    # Annotation (NEW)
]
```

### Weight 설계 (annotation_weight = 0.2)

- wRRF에서 rank 1: `0.2 / (60 + 1) ≈ 0.003`
- BM25 rank 1: `1.0 / (60 + 1) ≈ 0.016`
- Annotation은 BM25의 약 20% 영향력 → 보조 signal로 적절
- 주요 source가 아닌 **tiebreaker** 역할

## OpenAPI Annotation 자동 추론

**파일**: `ingest/openapi.py`

HTTP method → MCP annotation 매핑 (RFC 7231 기반):

```python
_ANNOTATION_BY_METHOD = {
    "get":     MCPAnnotations(read_only=True,  destructive=False, idempotent=True),
    "post":    MCPAnnotations(read_only=False, destructive=False, idempotent=False),
    "put":     MCPAnnotations(read_only=False, destructive=False, idempotent=True),
    "patch":   MCPAnnotations(read_only=False, destructive=False, idempotent=False),
    "delete":  MCPAnnotations(read_only=False, destructive=True,  idempotent=True),
}
```

OpenAPI ingest된 모든 도구에 자동 annotation → 별도 MCP source 없이도 annotation-aware retrieval 동작.

## MCP Tool Ingest

**파일**: `ingest/mcp.py`

```python
mcp_tools = [
    {"name": "...", "inputSchema": {...}, "annotations": {"readOnlyHint": True}}
]
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")
```

- `inputSchema` → `ToolParameter[]`
- `annotations` → `MCPAnnotations` (camelCase 자동 변환)
- `server_name` → `metadata["mcp_server"]` + tags

## 부가 통합

### OntologyBuilder

`builder.add_tool()` 시 node attributes에 `annotations` dict 저장 (camelCase MCP format).

### Similarity Stage 3

`_param_jaccard()`에 annotation 일치 보너스 추가:
- 양쪽 모두 annotation이 있을 때, 일치하는 hint 비율 × 0.1 가산
- 예: readOnly + destructive + idempotent 3개 중 3개 일치 → +0.1

## 테스트

| 파일 | 테스트 수 | 검증 내용 |
|------|----------|----------|
| `test_mcp_annotations.py` | 8 | 모델 직렬화/역직렬화, roundtrip |
| `test_ingest_mcp.py` | 10 | MCP ingest, parse_tool 자동 감지, ToolGraph 통합 |
| `test_intent_classifier.py` | 12 | 한/영 intent 분류, neutral, mixed |
| `test_annotation_scorer.py` | 9 | alignment score, mismatch, neutral |
| `test_annotation_retrieval.py` | 6 | E2E: read/write/delete query → 올바른 도구 상위 랭크 |
| `test_openapi_annotations.py` | 13 | HTTP method → annotation 추론, ingest 통합 |
