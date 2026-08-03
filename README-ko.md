<div align="center">

# graph-tool-call

**대규모 LLM 도구 카탈로그를 위한 그래프 기반 검색 엔진.**

목표 도구뿐 아니라 입력값을 만드는 선행 도구와, planner의 토큰 예산에
맞는 최소 schema bundle까지 찾습니다.

[공식 문서](https://sonaiengine.github.io/graph-tool-call/ko/) ·
[Quickstart](https://sonaiengine.github.io/graph-tool-call/ko/docs/getting-started/quickstart) ·
[PyPI](https://pypi.org/project/graph-tool-call/) ·
[벤치마크](docs/benchmarks.md)

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Core dependencies](https://img.shields.io/badge/core_dependencies-0-brightgreen.svg)](#설치)

[English](README.md) · 한국어

</div>

---

## 해결하려는 문제

"주문을 환불해줘"라는 질의에서 semantic search는 `refundOrder`를 찾을 수
있습니다. 하지만 이 API가 `order_id`를 요구하고 사용자에게 그 값이 없다면
목표 도구만 찾아서는 실행할 수 없습니다.

```text
findOrdersByEmail(email) -> order_id -> refundOrder(order_id)
```

도구가 많아질수록 모든 schema를 모델에 전달하는 방식도 context를 낭비하고
선택 품질을 떨어뜨립니다. graph-tool-call은 이를 flat similarity가 아니라
contract를 보존한 graph 검색 문제로 다룹니다.

제공 기능:

- OpenAPI, GraphQL introspection, MCP tools, Python 함수, structured catalog의
  deterministic ingest
- keyword, graph, optional embedding, MCP annotation을 결합한 target 검색
- 근거가 남는 target selection과 typed prerequisite 확장
- 토큰 예산을 고려한 contract-projected model schema
- collection readiness, failure reason, trace metadata
- OpenAI, Anthropic, LangChain v1, MCP, Docker, Kubernetes 통합

사용자 인증, tenant 정책, 승인, 제품별 실행은 host application이 담당합니다.

## 30초 데모

모델, API key, network 호출 없이 실행할 수 있습니다.

```bash
uvx graph-tool-call demo dependency-chain
```

```text
Selected target:
  refundOrder(order_id)

Required producer:
  findOrdersByEmail(email) -> order_id
  evidence: api_contract, openapi_link

Execution order:
  1. findOrdersByEmail
  2. refundOrder

Planner context:
  6 catalog tools -> 2 required tools
  estimated tokens: 1476 -> 160 (89% fewer)
```

이 데모는 실제 retriever, deterministic target selector, typed dependency
closure, schema admission pipeline을 사용합니다.

## 설치

Core graph/search package에는 외부 dependency가 없습니다. 필요한 기능만
extra로 설치합니다.

```bash
pip install graph-tool-call
pip install "graph-tool-call[openapi]"       # YAML OpenAPI
pip install "graph-tool-call[korean]"        # Kiwi tokenizer
pip install "graph-tool-call[langchain]"     # LangChain v1 middleware
pip install "graph-tool-call[mcp]"           # MCP server/proxy
pip install "graph-tool-call[all]"           # 모든 optional 기능
```

Python 3.10부터 3.14까지 CI에서 검증합니다.

## Build와 검색

### OpenAPI

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.graph.json",
)

for result in graph.retrieve_with_scores("새로운 pet을 등록해줘", top_k=5):
    print(result.tool.name, result.score, result.confidence)
```

OpenAPI ingest는 request/response schema, parameter 위치, content type,
security requirement, link, example, response envelope, typed
`consumes`/`produces` contract를 보존합니다. Swagger 2.0, OpenAPI 3.0,
OpenAPI 3.1을 지원합니다.

Agent에 연결하기 전에 collection을 진단할 수 있습니다.

```bash
graph-tool-call inspect-openapi ./openapi.json --json
graph-tool-call build-openapi-collection ./openapi.json -o collection.json
```

결과에는 단일 opaque score가 아니라 stable issue code, semantic coverage,
edge quality가 포함됩니다.

### 다른 source

```python
from graph_tool_call.ingest import ingest_source

openapi_result = ingest_source(openapi_document)
graphql_result = ingest_source(introspection_result)
mcp_result = ingest_source({"tools": mcp_tools}, format_hint="mcp-tools")
python_result = ingest_source([read_file, write_file])
```

모든 adapter는 normalized `ToolSchema`, capability metadata, unsupported
feature 진단을 같은 계약으로 반환합니다.

## 통합 방법

| 환경 | 권장 방식 | graph-tool-call 역할 |
| --- | --- | --- |
| Python application | `ToolGraph` / graphify API | ingest, 검색, 근거, dependency closure |
| OpenAI Responses/Chat | `patch_openai` | 요청별 function tool filtering |
| Anthropic Messages | `patch_anthropic` | 요청별 tool filtering |
| LangChain v1 | `create_tool_selection_middleware` | model-call tool selection |
| Claude Code, Cursor, Windsurf | MCP proxy | 여러 MCP backend를 3개 gateway tool로 축소 |
| OpenAI Agents, PydanticAI, Google ADK | remote MCP server | protocol-neutral 검색 service |
| Docker/Kubernetes | Streamable HTTP MCP | private 배포 service |

각 framework의 검증 범위는
[호환성 표](https://sonaiengine.github.io/graph-tool-call/ko/docs/integrations/ecosystem-compatibility)에서
확인할 수 있습니다. MCP protocol 호환이 모든 framework/cloud 버전을 직접
검증했다는 뜻은 아닙니다.

### OpenAI Responses

```python
from graph_tool_call.middleware import patch_openai

patch_openai(client, graph=graph, top_k=5)

response = client.responses.create(
    model=model_name,
    input="사용자 계정을 삭제해줘",
    tools=all_function_tools,
)
```

Web search 같은 hosted tool은 그대로 유지하며, 기존 Chat Completions도
호환됩니다.

### LangChain v1

```python
from langchain.agents import create_agent
from graph_tool_call.langchain import create_tool_selection_middleware

selection = create_tool_selection_middleware(langchain_tools, top_k=5)
agent = create_agent(
    model,
    tools=langchain_tools,
    middleware=[selection],
)
```

앞선 permission/feature middleware가 제거한 tool은 다시 추가하지 않습니다.

### MCP server

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

MCP endpoint는 `/mcp`, probe는 `/healthz`, `/readyz`입니다. 원격 endpoint는
private network 또는 인증된 gateway 뒤에 두어야 합니다.

### MCP proxy

```bash
graph-tool-call proxy \
  --config ./mcp-backends.json \
  --transport streamable-http
```

Local stdio, SSE, Streamable HTTP backend를 연결할 수 있습니다. Gateway mode는
`search_tools`, `get_tool_schema`, `call_backend_tool`을 노출하고 검색된 backend
tool이 보이게 되면 지원 client에 tool-list 변경 notification을 보냅니다.

## 재현 가능한 검증

Release headline은 CI에서 다시 만들 수 있는 model-free artifact만 사용합니다.
7개 commerce case에서 같은 selected target에 typed producer expansion을 적용한
결과입니다.

| Metric | Target only | Target + graph producers |
| --- | ---: | ---: |
| Required-producer recall | 14.3% | **100%** |
| Candidate plan coverage | 47.6% | **100%** |
| Candidate binding support | 14.3% | **100%** |
| Target Recall@5 | - | **100%** |

[v0.37.0 case-level artifact](benchmarks/results/releases/v0.37.0/dependency-chain-evidence.json)는
fixture hash, 모든 expected target/producer, replay command를 포함합니다.

```bash
make launch-evidence
make launch-evidence-check
```

이는 engine regression이며 LLM tool-calling 전체 정확도의 추정치나 SOTA 주장이
아닙니다. 외부 비교, model-loop 결과, confidence interval, 알려진 약점은
[Benchmark Results](docs/benchmarks.md)와
[논문 protocol](docs/research/paper-readiness-design.md)에 공개합니다.

## Production 경계

graph-tool-call은 retrieval/contract layer입니다. 운영 adapter에는 다음 책임이
남습니다.

- 사용자/service 인증
- tenant 권한과 승인 정책
- downstream secret/cookie 처리
- side effect 확인, cleanup, audit 보존
- provider/model lifecycle과 최종 응답 정책

Credential 원문을 graph artifact, tool description, trace record, model-visible
argument에 저장하지 마세요.

## 문서

| 문서 | 목적 |
| --- | --- |
| [Quickstart](https://sonaiengine.github.io/graph-tool-call/ko/docs/getting-started/quickstart) | 첫 검색, graph, readiness, execution |
| [Mental model](https://sonaiengine.github.io/graph-tool-call/ko/docs/getting-started/mental-model) | pipeline과 책임 경계 |
| [OpenAPI ingest](https://sonaiengine.github.io/graph-tool-call/ko/docs/build/openapi-ingestion) | contract 추출과 collection build |
| [Target selection](https://sonaiengine.github.io/graph-tool-call/ko/docs/search/target-selection) | ranking 근거와 deterministic guard |
| [Integrations](https://sonaiengine.github.io/graph-tool-call/ko/docs/integrations/ecosystem-compatibility) | framework, MCP, 배포 |
| [Roadmap](docs/roadmap.md) | 현재 제품/연구 우선순위 |

## 개발

```bash
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
poetry install --with dev --all-extras

poetry run ruff check .
poetry run ruff format --check .
poetry run pytest tests/ -q
```

[CONTRIBUTING.md](CONTRIBUTING.md)와
[release checklist](docs/release-checklist.md)를 참고하세요.

## License

[MIT](LICENSE)
