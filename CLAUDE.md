# graph-tool-call 개발 가이드

## 프로젝트 개요
LLM 에이전트를 위한 그래프 기반 도구 검색 엔진. NetworkX DiGraph + BM25 + Embedding + MCP Annotation + wRRF 기반 하이브리드 검색.

## 개발 환경

### 필수 도구
```bash
poetry install --with dev          # 기본 개발 환경
poetry install --with dev --all-extras  # 모든 optional dep 포함
```

### Lint & Format
```bash
poetry run ruff check .            # lint 검사
poetry run ruff format --check .   # format 검사
poetry run ruff format .           # 자동 format 적용
```

**중요**: 반드시 `poetry run ruff`를 사용할 것. 시스템 ruff나 `pip install ruff`는 버전이 다를 수 있음.
- pyproject.toml에 ruff 버전이 명시되어 있고, CI도 동일한 poetry 환경에서 실행함
- 커밋 전 `poetry run ruff format .` + `poetry run ruff check .` 통과 확인 필수

### 테스트
```bash
poetry run pytest tests/ -v        # 전체 테스트
poetry run pytest tests/ -q        # 간결 출력
```

## CI/CD (GitHub Actions)
- `.github/workflows/ci.yml`
- lint job: `poetry install --only dev` → `poetry run ruff check/format`
- test job: Python 3.10~3.14 매트릭스, `poetry install --with dev`
- **lint와 test 모두 poetry 환경에서 실행** (버전 일관성 보장)

## 코드 규칙

### Optional Dependency 패턴
```python
try:
    import numpy as np
except ImportError:
    np = None

def _require_numpy():
    if np is None:
        msg = "numpy required: pip install graph-tool-call[embedding]"
        raise ImportError(msg)
```
- extras별 그룹: `openapi`, `embedding`, `similarity`, `langchain`, `all`
- 에러 메시지에 설치 명령어 포함

### HTTP 호출
- `urllib.request` 사용 (requests/httpx 의존 안 함)
- `# noqa: S310` 주석으로 bandit 경고 억제

### 테스트 작성
- conftest.py 없음 — 각 테스트 파일에 헬퍼 함수 자체 정의
- `pytest.importorskip("module")` 으로 optional dep 테스트 처리
- mock 최소화, 실제 코드 실행 선호

### ruff 설정
```toml
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

## 커밋 규칙
- 한글 커밋 메시지, 구체적 내용 포함
- `git -c user.name="SonAIengine" -c user.email="sonsj97@gmail.com" commit`
- main 직접 push 가능 (개인 프로젝트)
- 커밋 전 체크리스트:
  1. `poetry run ruff check .`
  2. `poetry run ruff format --check .`
  3. `poetry run pytest tests/ -q`

## 주요 파일 구조
```
graph_tool_call/
  __init__.py          # public exports (MCPAnnotations, ToolSchema, ...), __version__
  tool_graph.py        # ToolGraph facade (모든 public API, from_url(), ingest_mcp_tools())
  core/tool.py         # MCPAnnotations, ToolSchema, parse_mcp_tool(), parse_tool()
  analyze/
    dependency.py      # 자동 의존관계 탐지
    similarity.py      # 5-Stage 중복 탐지 파이프라인 (annotation 보너스 포함)
  ingest/
    openapi.py         # OpenAPI 3.x 파서 (description fallback, HTTP→annotation 추론)
    mcp.py             # MCP tool list ingest (inputSchema + annotations 파싱)
    arazzo.py           # Arazzo 1.0.0 워크플로우 파서
  ontology/
    auto.py            # auto_organize (Auto + LLM-Auto 모드)
    builder.py         # OntologyBuilder (node에 annotations 저장)
    llm_provider.py    # OntologyLLM ABC + Ollama/OpenAI providers
    schema.py          # NodeType, RelationType enums
  retrieval/
    engine.py          # RetrievalEngine (4-source wRRF: BM25+Graph+Embedding+Annotation)
    intent.py          # QueryIntent + classify_intent() — 한/영 키워드 기반 zero-LLM
    annotation_scorer.py # score_annotation_match() + compute_annotation_scores()
    embedding.py       # EmbeddingIndex (sentence-transformers)
    search_llm.py      # SearchLLM ABC + providers
```

## 강건화 (Layered Resilience)

### Description Fallback
`ingest/openapi.py`의 `_operation_to_tool()`에서 summary/description이 비어있으면 자동 생성:
```
{METHOD} {path} [{tags}]  →  예: "GET /items [items]"
```

### from_url()
`ToolGraph.from_url(url)` — Swagger UI URL에서 swagger-config 자동 탐색 후 여러 spec 통합 ingest.
- `/swagger-ui/` 포함 URL → swagger-config 파싱 → urls[].url 추출
- 일반 spec URL → 직접 ingest
