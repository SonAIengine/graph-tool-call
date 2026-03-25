<div align="center">

# graph-tool-call

**LLM Agent를 위한 그래프 기반 Tool 검색 엔진**

의존성 제로. OpenAPI, MCP, Python 함수에서 tool을 수집하고,
tool 간 관계를 그래프로 조직화한 뒤, **필요한 tool만 정확하게 검색해 LLM에 전달**합니다.

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](https://pypi.org/project/graph-tool-call/)

<br>

| | Baseline (전체 tool) | graph-tool-call |
|---|:---:|:---:|
| **248 tools (K8s API)** | 12% 정확도 | **82% 정확도** |
| **1068 tools (GitHub 전체 API)** | 불가능 (context overflow) | **78% Recall@5** |
| **토큰 사용량** | 8,192 토큰 | 1,699 토큰 (**79% 절감**) |
| **지연시간 (임베딩 없이)** | — | **평균 2.7ms** |

<sub>qwen3:4b (4-bit) 기준 측정 — <a href="#벤치마크">전체 벤치마크 아래 참고</a></sub>

<br>

[English](README.md) · 한국어 · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

## graph-tool-call이란?

LLM Agent가 사용할 수 있는 tool은 빠르게 늘어나고 있습니다.
커머스 플랫폼은 **1,200개 이상의 API endpoint**를, 회사 내부 시스템은 여러 서비스에 걸쳐 **500개 이상의 함수**를 가질 수 있습니다.

문제는 단순합니다.

> **모든 tool 정의를 매번 context window에 넣을 수 없습니다.**

일반적인 해결책은 벡터 검색입니다.
tool 설명을 임베딩하고, 사용자 요청과 가장 가까운 tool을 찾는 방식입니다.

하지만 실제 tool 사용은 문서 검색과 다릅니다.

- 어떤 tool은 **다음 단계 tool**과 이어집니다.
- 어떤 tool은 **함께 호출되어야** 합니다.
- 어떤 tool은 **read-only**이고, 어떤 tool은 **destructive**입니다.
- 어떤 tool은 **이전에 호출한 tool의 결과를 전제로** 합니다.

즉, **tool은 독립적인 텍스트 조각이 아니라 워크플로우를 이루는 실행 단위**입니다.

**graph-tool-call**은 이 점에 집중합니다.
tool을 단순한 목록이 아니라 **관계가 있는 그래프**로 다루고, 다중 신호 하이브리드 검색으로 LLM에 필요한 tool만 전달합니다.

---

## 왜 필요한가?

예를 들어 사용자가 이렇게 말한다고 가정해보겠습니다.

> 주문을 취소하고 환불 처리해줘

벡터 검색은 `cancelOrder`를 찾을 수 있습니다.
하지만 실제 실행에는 보통 다음 흐름이 필요합니다.

```text
listOrders → getOrder → cancelOrder → processRefund
````

즉, 중요한 것은 “비슷한 tool 하나”가 아니라 **지금 필요한 tool과 다음에 이어질 tool까지 포함한 실행 흐름**입니다.

graph-tool-call은 이런 관계를 그래프로 모델링합니다.

```text
                    ┌──────────┐
          PRECEDES  │listOrders│  PRECEDES
         ┌─────────┤          ├──────────┐
         ▼         └──────────┘          ▼
   ┌──────────┐                    ┌───────────┐
   │ getOrder │                    │cancelOrder│
   └──────────┘                    └─────┬─────┘
                                        │ COMPLEMENTARY
                                        ▼
                                 ┌──────────────┐
                                 │processRefund │
                                 └──────────────┘
```

---

## 핵심 아이디어

graph-tool-call은 다음 파이프라인으로 동작합니다.

```text
OpenAPI / MCP / 코드 → 수집 → 분석 → 조직화 → 검색 → Agent
```

검색 단계에서는 여러 신호를 함께 사용합니다.

* **BM25**: 키워드 매칭
* **Graph traversal**: 관계 기반 확장
* **Embedding similarity**: 시맨틱 유사도
* **MCP annotations**: read-only / destructive / idempotent / open-world 힌트

이 신호들은 **weighted Reciprocal Rank Fusion (wRRF)** 으로 결합됩니다.

---

## 주요 기능

* **의존성 제로** — 코어는 Python 표준 라이브러리만으로 동작, 필요한 기능만 extras로 추가
* **OpenAPI / Swagger / MCP / Python 함수**에서 tool 자동 수집
* **tool 관계 그래프** 생성 및 활용
* **BM25 + 그래프 + 임베딩 + annotation** 기반 하이브리드 검색
* **History-aware retrieval**
* **Cross-encoder reranking**
* **MMR diversity**
* **LLM 기반 ontology 강화**
* **중복 tool 탐지 및 병합**
* **HTML / GraphML / Cypher** 내보내기
* **ai-api-lint 연동**으로 spec 자동 정리

---

## 언제 쓰면 좋은가?

graph-tool-call은 특히 다음 상황에서 효과적입니다.

* tool 수가 많아 **전체를 context에 넣기 어려울 때**
* 단순 유사도보다 **호출 순서 / 관계 정보**가 중요할 때
* **MCP annotation**을 반영한 retrieval이 필요할 때
* 여러 API spec 또는 여러 서비스의 tool을 **하나의 검색 계층으로 통합**할 때
* Agent가 이전 호출 이력을 바탕으로 **다음 tool을 더 잘 찾게 하고 싶을 때**

---

## 설치

코어 패키지는 **의존성 제로** — Python 표준 라이브러리만 사용합니다.
필요한 기능만 골라서 설치하세요:

```bash
pip install graph-tool-call                    # core (BM25 + graph) — 의존성 없음
pip install graph-tool-call[embedding]         # + 임베딩, cross-encoder reranker
pip install graph-tool-call[openapi]           # + OpenAPI YAML 지원
pip install graph-tool-call[mcp]              # + MCP 서버 모드
pip install graph-tool-call[all]               # 전부
```

<details>
<summary>모든 extras</summary>

| Extra | 설치되는 패키지 | 용도 |
|-------|----------------|------|
| `openapi` | pyyaml | YAML OpenAPI spec 파싱 |
| `embedding` | numpy | 시맨틱 검색 (외부 Ollama/OpenAI/vLLM 연결) |
| `embedding-local` | numpy, sentence-transformers | 로컬 sentence-transformers 모델 |
| `similarity` | rapidfuzz | 중복 tool 탐지 |
| `langchain` | langchain-core | LangChain 통합 |
| `visualization` | pyvis, networkx | HTML 그래프 내보내기, GraphML |
| `dashboard` | dash, dash-cytoscape | 인터랙티브 대시보드 |
| `lint` | ai-api-lint | API spec 자동 수정 |
| `mcp` | mcp | MCP 서버 모드 |

```bash
pip install graph-tool-call[lint]
pip install graph-tool-call[similarity]
pip install graph-tool-call[visualization]
pip install graph-tool-call[dashboard]
pip install graph-tool-call[langchain]
```

</details>

---

## 빠른 시작

### 30초 체험 (설치 없이)

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

```text
Query: "user authentication"
Source: https://petstore.swagger.io/v2/swagger.json (19 tools)
Results (5):

  1. getUserByName
     Get user by user name
  2. deleteUser
     Delete user
  3. createUser
     Create user
  4. loginUser
     Logs user into the system
  5. updateUser
     Updated user
```

### Python API

```python
from graph_tool_call import ToolGraph

# 공식 Petstore API에서 tool graph 생성
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# tool 검색
tools = tg.retrieve("create a new pet", top_k=5)
for t in tools:
    print(f"{t.name}: {t.description}")
```

이 스펙에서는 `top_k=5` 기준으로 **Recall@5 98.3%** 를 기록했습니다.

### 워크플로우 플래닝

벡터 검색은 개별 tool을 반환하지만, `plan_workflow()`는 선행 조건을 포함한 실행 순서 체인을 반환합니다. LLM Agent의 왕복 횟수를 3~4회에서 1회로 줄입니다.

```python
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

# 멀티스텝 워크플로우 자동 생성
plan = tg.plan_workflow("환불 처리")
for step in plan.steps:
    print(f"{step.order}. {step.tool.name} — {step.reason}")
# 1. getOrder — prerequisite for requestRefund
# 2. requestRefund — primary action

# 워크플로우 편집
plan.remove_step("listOrders")
plan.insert_step(0, "getOrder", tools=tg.tools, reason="주문 ID 필요")
plan.set_param_mapping("requestRefund", "order_id", "getOrder.response.id")

# 시각화 편집기 (브라우저에서 열림)
plan.open_editor(tools=tg.tools)

# 저장 / 로드
plan.save("refund_workflow.json")
```

### MCP 서버 (Claude Code, Cursor, Windsurf 등)

MCP 서버로 실행하면, MCP를 지원하는 모든 Agent가 설정 한 줄로 tool 검색을 사용할 수 있습니다:

```jsonc
// .mcp.json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve",
               "--source", "https://api.example.com/openapi.json"]
    }
  }
}
```

MCP 서버는 SSE 및 Streamable HTTP transport를 통한 원격 배포도 지원합니다:

```bash
# 원격 배포 (SSE transport)
graph-tool-call serve --source api.json --transport sse --host 0.0.0.0 --port 8000

# Streamable HTTP
graph-tool-call serve --source api.json --transport streamable-http --port 8000
```

원격 MCP 서버 클라이언트 설정:

```json
{
  "mcpServers": {
    "tool-search": {
      "url": "http://tool-search.internal:8000/sse"
    }
  }
}
```

서버는 6개의 tool을 노출합니다: `search_tools`, `get_tool_schema`, `execute_tool`, `list_categories`, `graph_info`, `load_source`.

### MCP Proxy (여러 MCP 서버 통합)

MCP 서버가 많으면 tool 이름 목록이 매 턴마다 쌓입니다.
MCP Proxy는 이걸 하나로 묶어서 **172개 tool → 3개 meta-tool**로 줄이고, 턴당 ~1,200 토큰을 절감합니다.

**Step 1.** 기존 MCP 서버 목록으로 `backends.json` 작성:

```jsonc
// ~/backends.json
{
  "backends": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp", "--headless"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/home"]
    },
    "my-api": {
      "command": "uvx",
      "args": ["some-mcp-server"],
      "env": { "API_KEY": "sk-..." }
    }
  },
  "top_k": 10,
  "cache_path": "~/.cache/mcp-proxy-cache.json"
}
```

> **Embedding은 선택사항.** Ollama가 있으면 `"embedding": "ollama/qwen3-embedding:0.6b"` 추가로 cross-language 검색 가능. 없어도 BM25 키워드 검색으로 동작합니다.

**Step 2.** Claude Code에 proxy 등록:

```bash
claude mcp add -s user tool-proxy -- \
  uvx "graph-tool-call[mcp]" proxy --config ~/backends.json
```

**Step 3.** 기존 개별 서버 제거 (중복 방지):

```bash
claude mcp remove playwright -s user
claude mcp remove filesystem -s user
claude mcp remove my-api -s user
```

**Step 4.** Claude Code 재시작 후 확인:

```bash
claude mcp list
# tool-proxy: ... - ✓ Connected
# (개별 서버는 제거됨)
```

완료. proxy는 `search_tools`, `get_tool_schema`, `call_backend_tool` 3개를 노출합니다. 검색 후 매칭된 tool은 **동적으로 등록**돼서 1-hop 직접 호출이 가능합니다.

<details>
<summary>대안: .mcp.json으로 설정</summary>

```jsonc
// .mcp.json (프로젝트 또는 글로벌)
{
  "mcpServers": {
    "tool-proxy": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "proxy",
               "--config", "/path/to/backends.json"]
    }
  }
}
```

</details>

### 직접 연동 (OpenAI, Ollama, vLLM, Azure 등)

`retrieve()`로 검색 후 OpenAI function-calling 포맷으로 변환. **모든 OpenAI 호환 API**에서 사용 가능:

```python
from openai import OpenAI
from graph_tool_call import ToolGraph
from graph_tool_call.langchain.tools import tool_schema_to_openai_function

# 그래프 생성
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

# 쿼리에 맞는 tool만 검색
tools = tg.retrieve("create a new pet", top_k=5)

# OpenAI function-calling 포맷으로 변환
openai_tools = [
    {"type": "function", "function": tool_schema_to_openai_function(t)}
    for t in tools
]

# 아무 provider나 사용 — OpenAI, Azure, Ollama, vLLM, llama.cpp 등
client = OpenAI()  # 또는 OpenAI(base_url="http://localhost:11434/v1") for Ollama
response = client.chat.completions.create(
    model="gpt-4o",
    tools=openai_tools,  # 전체 248개 대신 관련 5개만
    messages=[{"role": "user", "content": "create a new pet"}],
)
```

<details>
<summary>Anthropic Claude API</summary>

```python
from anthropic import Anthropic
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url("https://api.example.com/openapi.json")
tools = tg.retrieve("cancel an order", top_k=5)

# Anthropic tool 포맷으로 변환
anthropic_tools = [
    {
        "name": t.name,
        "description": t.description,
        "input_schema": {
            "type": "object",
            "properties": {
                p.name: {"type": p.type, "description": p.description}
                for p in t.parameters
            },
            "required": [p.name for p in t.parameters if p.required],
        },
    }
    for t in tools
]

client = Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=anthropic_tools,
    messages=[{"role": "user", "content": "주문 취소해줘"}],
    max_tokens=1024,
)
```

</details>

### SDK Middleware (코드 변경 없이)

이미 tool-calling 코드가 있으면 **한 줄 추가**로 자동 필터링:

```python
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

patch_openai(client, graph=tg, top_k=5)  # ← 이 줄만 추가

# 기존 코드 그대로 — 248개 tool이 들어가면, 관련 5개만 전달됨
response = client.chat.completions.create(
    model="gpt-4o",
    tools=all_248_tools,
    messages=messages,
)
```

```python
# Anthropic도 동일
from graph_tool_call.middleware import patch_anthropic
patch_anthropic(client, graph=tg, top_k=5)
```

### LangChain / LangGraph 연동

```bash
pip install graph-tool-call[langchain] langgraph
```

#### Gateway Tools (대규모 tool set 추천)

50~500+ tool을 **2개 meta-tool**로 변환. LLM이 검색 → 실행하는 구조:

```python
from graph_tool_call.langchain import create_gateway_tools

# Slack, GitHub, Jira, MS365 등 다양한 소스의 tool 62개
gateway = create_gateway_tools(all_tools, top_k=10)
# → [search_tools, call_tool] 2개만 agent에 전달

agent = create_react_agent(model=llm, tools=gateway)
result = agent.invoke({"messages": [("user", "PROJ-123 이슈를 Done으로 변경해줘")]})
```

| | 전체 tool 바인딩 | Gateway (2개) |
|---|:---:|:---:|
| **62 tools** | ~6,090 tokens/turn | ~475 tokens/turn |
| **토큰 절감** | — | **92%** |

#### 자동 필터링 Agent

매 턴 자동으로 관련 tool만 LLM에 바인딩:

```python
from graph_tool_call.langchain import create_agent

agent = create_agent(llm, tools=all_200_tools, top_k=5)
# 매 턴 유저 메시지 기반으로 ~5개 tool만 노출
```

<details>
<summary>LangChain Retriever (Document 반환)</summary>

```python
from graph_tool_call import ToolGraph
from graph_tool_call.langchain import GraphToolRetriever

tg = ToolGraph.from_url("https://api.example.com/openapi.json")

retriever = GraphToolRetriever(tool_graph=tg, top_k=5)
docs = retriever.invoke("cancel an order")

for doc in docs:
    print(doc.page_content)       # "cancelOrder: Cancel an existing order"
    print(doc.metadata["tags"])   # ["order"]
```

</details>

---

## 벤치마크

graph-tool-call은 두 가지를 검증합니다.

1. 검색된 일부 tool만 LLM에 줘도 성능을 유지하거나 개선하는가?
2. 검색기 자체가 정답 tool을 상위 K개 안에 잘 올리는가?

평가는 동일한 사용자 요청 세트에 대해 다음 구성을 비교했습니다.

* **baseline**: 전체 tool 정의를 LLM에 그대로 전달
* **retrieve-k3 / k5 / k10**: 검색된 상위 K개 tool만 전달
* **+ embedding / + ontology**: retrieve-k5 위에 시맨틱 검색과 LLM 기반 온톨로지 강화 추가

모델은 **qwen3:4b (4-bit, Ollama)** 를 사용했습니다.

### 평가 지표

* **Accuracy**: LLM이 최종적으로 올바른 tool을 선택했는가
* **Recall@K**: 검색 단계에서 정답 tool이 상위 K개 안에 포함되었는가
* **Avg tokens**: LLM에 전달된 평균 토큰 수
* **Token reduction**: baseline 대비 토큰 절감률

### 한눈에 보는 결과

* **작은 규모 API (19~50 tools)** 에서는 baseline도 이미 강합니다.
  이 구간에서 graph-tool-call의 주된 가치는 **정확도 유지에 가까운 상태에서 64~91% 토큰 절감**입니다.
* **큰 규모 API (248 tools)** 에서는 baseline이 **12%까지 붕괴**합니다.
  반면 graph-tool-call은 **78~82% 정확도**를 유지합니다. 이때는 최적화가 아니라 **필수 검색 계층**에 가깝습니다.

<details>
<summary>전체 파이프라인 비교</summary>

> **지표 해석**
>
> - **End-to-end Accuracy**: LLM이 최종적으로 올바른 tool 선택 또는 정답 workflow 수행에 성공했는가
> - **Gold Tool Recall@K**: retrieval 단계에서 **정답으로 지정한 canonical gold tool**이 상위 K개 안에 포함되었는가
> - 두 지표는 측정 대상이 다르므로 항상 같지 않습니다.
> - 특히 **대체 가능한 tool**이나 **동등한 workflow**도 정답으로 인정하는 평가에서는 `End-to-end Accuracy`가 `Gold Tool Recall@K`와 정확히 일치하지 않을 수 있습니다.
> - **baseline**은 retrieval 단계가 없으므로 `Gold Tool Recall@K`는 해당하지 않습니다.

| Dataset | Tool 수 | Pipeline | End-to-end Accuracy | Gold Tool Recall@K | Avg tokens | Token reduction |
|---|---:|---|---:|---:|---:|---:|
| Petstore | 19 | baseline | 100.0% | — | 1,239 | — |
| Petstore | 19 | retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| Petstore | 19 | retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| Petstore | 19 | retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |
| GitHub | 50 | baseline | 100.0% | — | 3,302 | — |
| GitHub | 50 | retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| GitHub | 50 | retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| GitHub | 50 | retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |
| Mixed MCP | 38 | baseline | 96.7% | — | 2,741 | — |
| Mixed MCP | 38 | retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| Mixed MCP | 38 | retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| Mixed MCP | 38 | retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |
| Kubernetes core/v1 | 248 | baseline | 12.0% | — | 8,192 | — |
| Kubernetes core/v1 | 248 | retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding | 80.0% | 94.0% | 1,728 | 78.9% |
| Kubernetes core/v1 | 248 | retrieve-k5 + ontology | **82.0%** | 96.0% | 1,699 | 79.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding + ontology | **82.0%** | **98.0%** | 1,924 | 76.5% |

**이 표를 어떻게 읽으면 되는가**

- **baseline**은 retrieval 없이 전체 tool 정의를 그대로 LLM에 넣은 결과입니다.
- **retrieve-k** 계열은 검색된 일부 tool만 LLM에 주므로, retrieval 품질과 LLM 선택 능력이 함께 성능에 영향을 줍니다.
- 따라서 baseline 정확도가 100%라고 해서 retrieve-k 정확도도 100%여야 하는 것은 아닙니다.
- `Gold Tool Recall@K`는 retrieval이 canonical gold tool을 top-k 안에 넣었는지를 측정하고,
  `End-to-end Accuracy`는 최종 task 수행이 성공했는지를 측정합니다.
- 이 때문에 대체 가능한 tool이나 동등한 workflow를 허용하는 평가에서는 두 값이 정확히 일치하지 않을 수 있습니다.

**핵심 해석**

- **Petstore / GitHub / Mixed MCP**처럼 tool 수가 적거나 중간 규모인 경우, baseline도 이미 강합니다.
  이 구간에서 graph-tool-call의 주요 가치는 **정확도를 크게 해치지 않으면서 토큰을 대폭 줄이는 것**입니다.
- **Kubernetes core/v1 (248 tools)**처럼 tool 수가 많아지면 baseline은 컨텍스트 과부하로 급격히 무너집니다.
  반면 graph-tool-call은 검색으로 후보를 좁혀 **12.0% → 78.0~82.0%**까지 성능을 회복합니다.
- 실무적으로는 **retrieve-k5**가 가장 좋은 기본값입니다.
  토큰 효율과 성능 균형이 좋고, 큰 데이터셋에서는 embedding / ontology 추가 시 추가 개선도 얻을 수 있습니다.

</details>

### 검색기 자체 성능: 정답 tool을 상위 K개 안에 찾는가?

아래 표는 **LLM 이전 단계**, 즉 retrieval 자체의 품질만 따로 측정한 결과입니다.
여기서는 **BM25 + 그래프 탐색만 사용**했으며, 임베딩과 ontology는 포함하지 않았습니다.

> **지표 해석**
>
> - **Gold Tool Recall@K**: retrieval 단계에서 **정답으로 지정한 canonical gold tool**이 상위 K개 안에 포함되었는가
> - 이 표는 **최종 LLM 선택 정확도**가 아니라, **검색기가 후보군을 얼마나 잘 구성하는지**를 보여줍니다.
> - 따라서 이 표는 위의 **End-to-end Accuracy** 표와 함께 읽어야 합니다.
> - retrieval이 gold tool을 top-k에 넣더라도, 최종 LLM이 항상 정답을 고르는 것은 아닙니다.
> - 반대로 end-to-end 평가에서 **대체 가능한 tool**이나 **동등한 workflow**를 정답으로 인정하는 경우, 최종 정확도와 gold recall은 정확히 일치하지 않을 수 있습니다.

| Dataset | Tool 수 | Gold Tool Recall@3 | Gold Tool Recall@5 | Gold Tool Recall@10 |
|---|---:|---:|---:|---:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub | 50 | 87.5% | **87.5%** | 92.5% |
| Mixed MCP | 38 | 93.3% | **96.7%** | 100.0% |
| Kubernetes core/v1 | 248 | 82.0% | **91.0%** | 92.0% |

### 이 표를 어떻게 읽으면 되는가

- **Gold Tool Recall@K**는 retrieval이 정답 tool을 후보군 안에 포함시키는 능력을 보여줍니다.
- 작은 데이터셋에서는 `k=5`만으로도 높은 recall을 확보할 수 있습니다.
- 큰 데이터셋에서는 `k`를 늘릴수록 recall이 올라가지만, 그만큼 LLM에 전달되는 토큰도 증가합니다.
- 따라서 실제 운영에서는 recall만이 아니라 **토큰 비용**과 **최종 end-to-end accuracy**를 함께 봐야 합니다.

### 핵심 해석

- **Petstore / Mixed MCP**에서는 `k=5`만으로도 거의 모든 정답 tool을 후보군에 포함시킵니다.
- **GitHub**에서는 `k=5`와 `k=10` 사이에 recall 차이가 있어, 더 높은 recall이 필요하면 `k=10`이 유리할 수 있습니다.
- **Kubernetes core/v1**처럼 tool 수가 큰 경우에는 `k=5`에서도 이미 **91.0%**의 gold recall을 확보합니다.
  즉, 검색 단계만으로도 후보군을 크게 압축하면서 상당수 정답 tool을 유지할 수 있습니다.
- 전반적으로 **`retrieve-k5`가 가장 실용적인 기본값**입니다.
  `k=3`은 더 가볍지만 일부 정답을 놓치고, `k=10`은 recall 이득 대비 토큰 비용이 커질 수 있습니다.

### 가장 어려운 경우: embedding과 ontology는 언제 도움이 되는가?

가장 큰 데이터셋인 **Kubernetes core/v1 (248 tools)** 에서, `retrieve-k5` 위에 추가 신호를 붙여 비교했습니다.

| Pipeline | End-to-end Accuracy | Gold Tool Recall@5 | 해석 |
|---|---:|---:|---|
| retrieve-k5 | 78.0% | 91.0% | BM25 + 그래프만으로도 strong baseline |
| + embedding | 80.0% | 94.0% | 의미적으로 비슷하지만 표현이 다른 query를 더 잘 회수 |
| + ontology | **82.0%** | 96.0% | LLM이 생성한 키워드/예시 질의가 검색 품질을 크게 개선 |
| + embedding + ontology | **82.0%** | **98.0%** | 정확도는 유지, gold recall은 최고치 |

### 정리

- **embedding**은 BM25가 놓치는 **시맨틱 유사성**을 보완합니다.
- **ontology**는 tool 설명이 짧거나 비표준적일 때 **검색 가능한 표현 자체를 확장**합니다.
- 둘을 함께 쓰면 end-to-end accuracy 상승 폭은 제한적일 수 있지만, **정답 tool을 후보군에 포함시키는 능력은 가장 강해집니다**.

### 경쟁 벤치마크 (retrieval 전략 비교)

9개 데이터셋(19~1068 tools)에 걸쳐 6가지 retrieval 전략을 비교했습니다:

| 전략 | Recall@5 | MRR | 지연시간 |
|---|:---:|:---:|:---:|
| Vector Only (≈bigtool) | 96.8% | 0.897 | 176ms |
| BM25 Only | 91.6% | 0.819 | 1.5ms |
| BM25 + Graph (기본값) | 91.6% | 0.819 | 14ms |
| Full Pipeline (임베딩 포함) | 96.8% | 0.897 | 172ms |

**핵심 발견**: 임베딩 없이도 BM25+Graph는 91.6% Recall을 달성합니다 — 벡터 검색 대비 65배 빠른 속도에서 경쟁력 있는 성능입니다. 임베딩을 활성화하면 순수 벡터 검색과 동일한 성능을 냅니다.

### 대규모 테스트: 1068 tools (GitHub 전체 API)

| 전략 | Recall@5 | MRR | Miss% |
|---|:---:|:---:|:---:|
| Vector Only | 88.0% | 0.761 | 12.0% |
| BM25 + Graph | 78.0% | 0.643 | 22.0% |
| Full Pipeline | 88.0% | 0.761 | 12.0% |

### LangChain 에이전트 벤치마크 (200 tools)

200개의 간단한 tool을 등록하고 **LangChain** 에이전트를 통해 호출했을 때의 end-to-end 정확도입니다.

* **Direct (D)**: 200개의 tool 정의를 한 번에 LLM에 전달
* **Graph (G)**: graph-tool-call 게이트웨이를 통해 tool 관리 (search → call, 2턴)

| 모델 | D-정확 | G-정확 | D-턴 | G-턴 | D-최소% | G-최소% | D-토큰 | G-토큰 | 절감률 | D-시간 | G-시간 | D-Tool | G-Tool | D-LLM | G-LLM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4.1 | 60.0% | 80.0% | 1.0 | 2.0 | 100% | 100% | 52,587 | 6,639 | 87.4% | 15.5s | 17.6s | 0.00s | 0.04s | 15.50s | 17.55s |
| gpt-5.2 | 60.0% | **100.0%** | 1.0 | 2.0 | 100% | 100% | 53,645 | 10,508 | 80.4% | 20.5s | 17.1s | 0.00s | 0.03s | 20.48s | 17.06s |
| gpt-5.4 | 60.0% | **100.0%** | 1.0 | 2.0 | 100% | 100% | 60,035 | 14,049 | 76.6% | 18.2s | 17.0s | 0.00s | 0.06s | 18.23s | 16.96s |
| claude-sonnet-4-20250514 | 100.0% | 100.0% | 1.0 | 2.0 | 100% | 100% | 196,183 | 17,349 | 91.2% | 58.2s | 49.4s | 0.00s | 0.03s | 58.23s | 49.35s |
| claude-sonnet-4-6 | 100.0% | 100.0% | 1.0 | 2.0 | 100% | 100% | 198,665 | 20,074 | 89.9% | 67.0s | 69.4s | 0.00s | 0.03s | 67.02s | 69.33s |
| claude-haiku-4-5 | 100.0% | 100.0% | 1.0 | 2.0 | 100% | 100% | 197,845 | 19,714 | 90.0% | 23.7s | 22.8s | 0.00s | 0.03s | 23.73s | 22.73s |

> **컬럼 범례**: 정확 = 정확도, 턴 = 평균 에이전트 턴 수, 최소% = 최소 tool 호출 성공률, 토큰 = 총 소비 토큰, 절감률 = 토큰 절감(D→G), 시간 = 벽시계 시간, Tool = tool 실행 시간, LLM = LLM 추론 시간

**핵심 발견**

- GPT 계열 모델은 200개 tool을 직접 전달하면 **정확도가 60%** 로 떨어지지만, graph-tool-call을 사용하면 **80~100%** 로 회복됩니다.
- Claude 계열 모델은 어느 방식이든 100% 정확도를 유지하지만, graph-tool-call이 **89~91% 토큰을 절감**합니다.
- Graph 모드는 1턴이 추가되지만(search → call), 컨텍스트가 줄어들어 총 지연 시간은 비슷하거나 오히려 감소합니다.
- 모든 모델에서 토큰 절감률은 **76.6%~91.2%** 범위입니다.

### 직접 재현하기

```bash
# 검색 품질 측정 (빠름, LLM 불필요)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# 파이프라인 벤치마크 (LLM 비교)
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# 베이스라인 저장 및 비교
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

---

## 기본 사용법

### OpenAPI / Swagger에서 생성

```python
from graph_tool_call import ToolGraph

# 파일에서 (JSON / YAML)
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# URL에서 — Swagger UI의 모든 spec 그룹 자동 탐색
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# 캐싱 — 한 번 빌드, 즉시 재사용
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",
)

# 지원: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
```

### MCP 서버 tool에서 생성

```python
from graph_tool_call import ToolGraph

mcp_tools = [
    {
        "name": "read_file",
        "description": "파일 읽기",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "delete_file",
        "description": "파일 영구 삭제",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]

tg = ToolGraph()
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

tools = tg.retrieve("임시 파일 삭제", top_k=5)
```

MCP annotation (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)은 검색 신호로 활용됩니다.
조회 쿼리는 read-only tool을, 삭제 쿼리는 destructive tool을 더 우선적으로 랭크할 수 있습니다.

### MCP 서버 URL에서 바로 수집

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Public MCP endpoint
tg.ingest_mcp_server("https://mcp.example.com/mcp")

# 로컬/사설 MCP endpoint는 명시적으로 허용해야 함
tg.ingest_mcp_server(
    "http://127.0.0.1:3000/mcp",
    allow_private_hosts=True,
)
```

`ingest_mcp_server()`는 HTTP JSON-RPC `tools/list`를 호출해 tool 목록을 가져오고,
annotation을 보존한 채 graph에 등록합니다.

원격 수집 기본 보안 정책:
- private / localhost host는 기본 차단
- 원격 응답 크기 제한
- redirect 횟수 제한
- 예상하지 않은 content-type 차단

### Python 함수에서 생성

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """파일 내용을 읽는다."""

def write_file(path: str, content: str) -> None:
    """파일에 내용을 쓴다."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
```

type hint에서 파라미터를, docstring에서 설명을 자동 추출합니다.

### 수동 tool 등록

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

tg.add_tools([
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "도시의 현재 날씨 조회",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    },
])

tg.add_relation("get_weather", "get_forecast", "complementary")
```

---

## 임베딩 기반 하이브리드 검색

BM25 + 그래프 위에 임베딩 기반 시맨틱 검색을 추가할 수 있습니다.
무거운 의존성 없이 외부 embedding 서버(Ollama, OpenAI, vLLM 등)를 연결하거나, 로컬 sentence-transformers를 사용할 수 있습니다.

```bash
pip install graph-tool-call[embedding]           # numpy만 (~20MB)
pip install graph-tool-call[embedding-local]      # + sentence-transformers (~2GB, 로컬 모델)
```

```python
# Ollama (추천 — 가볍고 cross-language 지원)
tg.enable_embedding("ollama/qwen3-embedding:0.6b")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# vLLM / llama.cpp / OpenAI-호환 서버
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")

# Sentence-transformers (embedding-local extra 필요)
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# 커스텀 callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

임베딩 활성화 시 가중치가 자동 재조정됩니다. 직접 튜닝도 가능합니다.

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

---

## 저장과 로드

한 번 빌드한 그래프는 그대로 저장하고 재사용할 수 있습니다.

```python
# 저장
tg.save("my_graph.json")

# 로드
tg = ToolGraph.load("my_graph.json")

# from_url()에서 cache= 옵션으로 자동 저장/로드
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

전체 그래프 구조(노드, 엣지, 관계 타입, 가중치)가 보존됩니다.

임베딩 검색을 켠 상태에서 저장하면 아래도 함께 보존됩니다.
- embedding vector
- 복원 가능한 embedding provider 설정
- retrieval weights
- diversity 설정

즉 `ToolGraph.load()` 후 embedding을 다시 만들지 않아도 hybrid retrieval 상태를 바로 복원할 수 있습니다.

---

## 고급 기능

### Cross-Encoder 리랭킹

Cross-encoder 모델로 2차 리랭킹을 수행합니다.

```python
tg.enable_reranker()  # 기본: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("주문 취소", top_k=5)
```

wRRF로 먼저 후보를 좁힌 뒤, `(query, tool_description)` 쌍을 함께 인코딩해 더 정밀하게 순위를 조정합니다.

### MMR 다양성

중복되는 결과를 줄이고 더 다양한 후보를 확보합니다.

```python
tg.enable_diversity(lambda_=0.7)
```

### History-aware 검색

이전에 호출한 tool 이름을 넘기면 다음 단계 검색이 개선됩니다.

```python
# 첫 호출
tools = tg.retrieve("주문 찾기")
# → [listOrders, getOrder, ...]

# 두 번째 호출
tools = tg.retrieve("이제 취소해줘", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
```

이미 사용한 tool은 하향되고, 그래프상 다음 단계에 가까운 tool은 상향됩니다.

### wRRF 가중치 튜닝

각 신호의 기여도를 조정할 수 있습니다.

```python
tg.set_weights(
    keyword=0.2,     # BM25 텍스트 매칭
    graph=0.5,       # 그래프 탐색
    embedding=0.3,   # 시맨틱 유사도
    annotation=0.2,  # MCP annotation 매칭
)
```

### LLM 강화 온톨로지

LLM으로 더 풍부한 tool 온톨로지를 구성할 수 있습니다.
카테고리 생성, 관계 추론, 검색 키워드 확장에 유용합니다.

```python
tg.auto_organize(llm="ollama/qwen2.5:7b")
tg.auto_organize(llm=lambda p: my_llm(p))
tg.auto_organize(llm=openai.OpenAI())
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")
```

<details>
<summary>지원하는 LLM 입력</summary>

| 입력                                   | 래핑 타입                         |
| ------------------------------------ | ----------------------------- |
| `OntologyLLM` 인스턴스                   | 그대로 사용                        |
| `callable(str) -> str`               | `CallableOntologyLLM`         |
| OpenAI 클라이언트 (`chat.completions` 보유) | `OpenAIClientOntologyLLM`     |
| `"ollama/model"`                     | `OllamaOntologyLLM`           |
| `"openai/model"`                     | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"`                    | litellm.completion 래퍼         |

</details>

### 중복 탐지

여러 API spec 간 중복된 tool을 찾아 병합할 수 있습니다.

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### 내보내기와 시각화

```python
# 인터랙티브 HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (Gephi, yEd)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint 통합

[ai-api-lint](https://github.com/SonAIengine/ai-api-lint)로 OpenAPI spec을 수집 전에 자동 정리할 수 있습니다.

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)
```

---

## 왜 벡터 검색만으로는 부족한가?

| 시나리오                     | 벡터만 사용             | graph-tool-call                                       |
| ------------------------ | ------------------ | ----------------------------------------------------- |
| *"주문 취소해줘"*              | `cancelOrder` 반환   | `listOrders → getOrder → cancelOrder → processRefund` |
| *"파일 읽고 저장"*             | `read_file` 반환     | `read_file` + `write_file` (COMPLEMENTARY 관계)         |
| *"오래된 레코드 삭제"*           | "삭제"와 매칭되는 아무 tool | destructive tool 우선 랭크                                |
| *"이제 취소해줘"* (history)    | 컨텍스트 없음            | 이미 사용한 tool 하향, 다음 단계 tool 상향                         |
| 여러 Swagger spec에 중복 tool | 결과에 중복 포함          | cross-source 자동 중복 제거                                 |
| 1,200개 API endpoint      | 느리고 노이즈 많음         | 카테고리화 + 그래프 탐색으로 정밀 검색                                |

---

## CLI 레퍼런스

```bash
# 원라인 검색 (수집 + 검색을 한 번에)
graph-tool-call search "cancel order" --source https://api.example.com/openapi.json
graph-tool-call search "delete user" --source ./openapi.json --scores --json

# MCP 서버
graph-tool-call serve --source https://api.example.com/openapi.json
graph-tool-call serve --graph prebuilt.json
graph-tool-call serve -s https://api1.com/spec.json -s https://api2.com/spec.json

# 그래프 빌드 및 저장
graph-tool-call ingest https://api.example.com/openapi.json -o graph.json
graph-tool-call ingest ./spec.yaml --embedding --organize

# 사전 빌드된 그래프에서 검색
graph-tool-call retrieve "query" -g graph.json -k 10

# 분석, 시각화, 대시보드
graph-tool-call analyze graph.json --duplicates --conflicts
graph-tool-call visualize graph.json -f html
graph-tool-call info graph.json
graph-tool-call dashboard graph.json --port 8050
```

---

## 전체 API 레퍼런스

<details>
<summary><code>ToolGraph</code> 메서드</summary>

| 메서드                            | 설명                          |
| ------------------------------ | --------------------------- |
| `add_tool(tool)`               | 단일 tool 추가 (포맷 자동 감지)       |
| `add_tools(tools)`             | 여러 tool 추가                  |
| `ingest_openapi(source)`       | OpenAPI / Swagger spec에서 수집 |
| `ingest_mcp_tools(tools)`      | MCP tool list에서 수집          |
| `ingest_mcp_server(url)`       | MCP HTTP 서버에서 직접 수집       |
| `ingest_functions(fns)`        | Python callable에서 수집        |
| `ingest_arazzo(source)`        | Arazzo 1.0.0 워크플로우 spec 수집  |
| `from_url(url, cache=...)`     | Swagger UI 또는 spec URL에서 빌드 |
| `add_relation(src, tgt, type)` | 수동 관계 추가                    |
| `auto_organize(llm=...)`       | tool 자동 분류                  |
| `build_ontology(llm=...)`      | 전체 온톨로지 빌드                  |
| `retrieve(query, top_k=10)`    | tool 검색                     |
| `validate_tool_call(call)`     | tool call 검증 및 자동 교정        |
| `assess_tool_call(call)`       | 실행 정책 기준 `allow/confirm/deny` 판정 |
| `enable_embedding(provider)`   | 하이브리드 임베딩 검색 활성화            |
| `enable_reranker(model)`       | cross-encoder 리랭킹 활성화       |
| `enable_diversity(lambda_)`    | MMR 다양성 활성화                 |
| `set_weights(...)`             | wRRF 융합 가중치 튜닝              |
| `find_duplicates(threshold)`   | 중복 tool 탐지                  |
| `merge_duplicates(pairs)`      | 탐지된 중복 병합                   |
| `apply_conflicts()`            | CONFLICTS_WITH 엣지 감지/추가     |
| `analyze()`                    | 운영 분석 리포트 생성                |
| `save(path)` / `load(path)`    | 직렬화 / 역직렬화                  |
| `export_html(path)`            | 인터랙티브 HTML 시각화 내보내기         |
| `export_graphml(path)`         | GraphML 포맷 내보내기             |
| `export_cypher(path)`          | Neo4j Cypher 문장 내보내기        |
| `dashboard_app()` / `dashboard()` | 대시보드 생성 / 실행             |
| `suggest_next(tool, history=...)` | 그래프 기반 다음 tool 추천        |

</details>

---

## 기능 비교

| 기능      | 벡터만 사용하는 솔루션 | graph-tool-call                         |
| ------- | ------------ | --------------------------------------- |
| Tool 소스 | 수동 등록        | Swagger / OpenAPI / MCP 자동 수집           |
| 검색 방식   | 단순 벡터 유사도    | 다단계 하이브리드 (wRRF + rerank + MMR)         |
| 행동적 의미  | 없음           | MCP annotation-aware retrieval          |
| Tool 관계 | 없음           | 6가지 관계 타입, 자동 감지                        |
| 호출 순서   | 없음           | 상태 머신 + CRUD + response→request 데이터 플로우 |
| 중복 제거   | 없음           | Cross-source 중복 탐지                      |
| 온톨로지    | 없음           | Auto / LLM-Auto 모드                      |
| History | 없음           | 사용한 tool 하향, 다음 단계 상향                   |
| Spec 품질 | 좋은 spec 가정   | ai-api-lint 자동 수정 통합                    |
| LLM 의존성 | 필수           | 선택 (없어도 동작, 있으면 더 좋음)                   |

---

## 문서

| 문서                                          | 설명                                                |
| ------------------------------------------- | ------------------------------------------------- |
| [아키텍처](docs/architecture/overview.md)       | 시스템 개요, 파이프라인 레이어, 데이터 모델                         |
| [WBS](docs/wbs/)                            | Work Breakdown Structure — Phase 0~4 진행 상황        |
| [설계](docs/design/)                          | 알고리즘 설계 — spec 정규화, 의존성 감지, 검색 모드, 호출 순서, 온톨로지 모드 |
| [리서치](docs/research/)                       | 경쟁 분석, API 규모 데이터, 커머스 패턴                         |
| [OpenAPI 가이드](docs/design/openapi-guide.md) | 더 좋은 tool graph를 만드는 API spec 작성법                 |

---

## 기여하기

기여를 환영합니다.

```bash
# 개발 환경 설정
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev

# 테스트 실행
poetry run pytest -v

# 린트
poetry run ruff check .
poetry run ruff format --check .

# 벤치마크 실행
python -m benchmarks.run_benchmark -v
```

---

## 라이선스

[MIT](LICENSE)
