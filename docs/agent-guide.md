# graph-tool-call Agent Guide

이 문서는 `graph-tool-call` 저장소에서 Claude Code와 Codex가 함께 작업할 때 사용하는 공통 기준 문서다.
프로젝트 규칙이 바뀌면 이 파일을 먼저 수정하고, 루트의 `CLAUDE.md`와 `AGENTS.md`는 진입 안내만 유지한다.

## 프로젝트 개요
- `graph-tool-call`은 LLM 에이전트를 위한 그래프 기반 도구 검색 엔진이다.
- OpenAPI, MCP, Python 함수에서 도구를 수집하고, 관계를 그래프로 구성한 뒤 필요한 도구만 검색한다.
- 핵심 조합은 NetworkX DiGraph + BM25 + optional embedding/reranking + MCP annotation + weighted RRF다.

## 개발 환경

### 설치
```bash
poetry install --with dev
poetry install --with dev --all-extras
```

### Lint / Format
```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run ruff format .
```

중요 사항:
- 반드시 `poetry run ruff`를 사용한다.
- 시스템 `ruff`나 별도 `pip install ruff`는 버전 차이로 CI와 어긋날 수 있다.

### 테스트
```bash
poetry run pytest tests/ -v
poetry run pytest tests/ -q
```

## CI 기준
- 워크플로우: `.github/workflows/ci.yml`
- lint는 Poetry 환경에서 `ruff check`, `ruff format --check` 기준으로 돈다.
- test는 Python 3.10~3.14 매트릭스로 돈다.

## 코드 규칙

### Optional Dependency 패턴
optional feature는 import guard를 유지한다.

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

규칙:
- extras 그룹은 `openapi`, `embedding`, `similarity`, `langchain`, `visualization`, `lint`, `mcp`, `all`
- optional dependency 관련 예외 메시지에는 설치 힌트를 포함한다.
- extras 기능에 hard import를 추가하지 않는다.

### HTTP 호출
- 기본적으로 `urllib.request`를 사용한다.
- 안전한 URL open에 대해 Bandit 경고가 필요하면 `# noqa: S310`를 사용한다.

### 테스트 작성
- 공용 `conftest.py` 없이, 각 테스트 파일에서 필요한 헬퍼를 작게 둔다.
- optional dependency 테스트는 `pytest.importorskip(...)`를 사용한다.
- mock 남발보다 실제 코드 실행을 선호한다.

### Ruff
```toml
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

## 작업 마감 전 체크
아래 순서로 확인한다.

1. `poetry run ruff check .`
2. `poetry run ruff format --check .`
3. `poetry run pytest tests/ -q`

## 주요 경로
```text
graph_tool_call/
  __init__.py                # public exports, __version__
  __main__.py                # CLI entry point (search/serve/ingest/...)
  tool_graph.py              # public facade
  mcp_server.py              # MCP server (FastMCP, stdio/sse)
  mcp_proxy.py               # MCP proxy (aggregate + filter backends)
  middleware.py              # SDK middleware (OpenAI/Anthropic patch)
  core/tool.py               # ToolSchema, MCPAnnotations, parsing
  ingest/openapi.py          # OpenAPI ingest
  ingest/mcp.py              # MCP ingest
  ingest/functions.py        # Python function ingest
  ontology/auto.py           # auto organize
  ontology/builder.py        # ontology graph build
  ontology/schema.py         # NodeType, RelationType
  retrieval/engine.py        # hybrid retrieval
  retrieval/intent.py        # query intent classification
  retrieval/annotation_scorer.py
  retrieval/embedding.py
  analyze/dependency.py      # dependency detection
  analyze/similarity.py      # duplicate detection
  visualization/             # HTML, GraphML, Cypher export
tests/
docs/
```

## 동작 메모
- `ToolGraph.from_url(url)`은 direct spec URL과 Swagger UI URL을 모두 지원한다.
- OpenAPI ingest는 summary/description이 비어 있을 때 fallback description을 만든다.
- 검색 품질은 단일 유사도보다 keyword, graph, embedding, annotation을 함께 쓰는 쪽에 맞춰져 있다.

## 문서 운영 원칙
- 공통 프로젝트 규칙은 이 문서에 쓴다.
- Claude 전용 메모는 `CLAUDE.md`에 최소한으로 둔다.
- Codex 전용 메모는 `AGENTS.md`에 최소한으로 둔다.
