<div align="center">

# graph-tool-call

**LLM Agent를 위한 그래프 기반 Tool 검색 엔진**

수집, 분석, 조직화, 검색.

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · 한국어 · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

## 문제

LLM Agent가 사용할 수 있는 tool이 점점 많아지고 있습니다. 커머스 플랫폼은 **1,200개 이상의 API endpoint**를, 회사 내부 시스템은 여러 서비스에 걸쳐 **500개 이상의 함수**를 가질 수 있습니다.

하지만 한계가 있습니다: **모든 tool을 context window에 넣을 수 없습니다.**

일반적인 해결책은 벡터 검색 — tool 설명을 임베딩하고, 가장 가까운 것을 찾습니다. 동작은 하지만, 중요한 것을 놓칩니다:

> **Tool은 독립적으로 존재하지 않습니다. 서로 관계가 있습니다.**

사용자가 *"주문을 취소하고 환불 처리해줘"*라고 말하면, 벡터 검색은 `cancelOrder`를 찾을 수 있습니다. 하지만 주문 ID를 얻기 위해 먼저 `listOrders`를 호출해야 하고, 이후에 `processRefund`가 와야 한다는 것은 모릅니다. 이것들은 단순히 비슷한 tool이 아닙니다 — **워크플로우**입니다.

## 해결책

**graph-tool-call**은 tool 간 관계를 그래프로 모델링하고, 다중 신호 하이브리드 파이프라인으로 검색합니다:

```
OpenAPI/MCP/코드 → [수집] → [분석] → [조직화] → [검색] → Agent
                    (변환)  (관계발견) (그래프)   (wRRF 하이브리드)
```

**4-source wRRF 융합**: BM25 키워드 매칭 + 그래프 탐색 + 임베딩 유사도 + MCP annotation 스코어링 — weighted Reciprocal Rank Fusion으로 결합.

```
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

## 벤치마크

> **LLM이 올바른 tool을 고를 수 있을까?**
> LLM에게 사용자 요청과 tool 정의를 주고, 올바른 tool을 호출하는지 확인했습니다.
> - **사용 전**: **전체** tool 정의를 LLM에 전달.
> - **사용 후**: graph-tool-call이 검색한 **상위 5개**만 전달.

모든 벤치마크는 누구나 다운로드하고 재현할 수 있는 공개 스펙을 사용합니다: [Petstore OpenAPI](https://petstore3.swagger.io), [Kubernetes core/v1 API](https://github.com/kubernetes/kubernetes), GitHub REST API, MCP tool 서버.

### 결과: graph-tool-call이 LLM을 도와주는가?

모델: qwen3.5:4b (4-bit 양자화, Ollama). 각 쿼리마다 LLM이 올바른 tool을 호출하는지 평가.

| API | 전체 tool 수 | 사용 전 (전체 tool → LLM) | 사용 후 (top-5 → LLM) | 변화 |
|-----|:----------:|:----------------------:|:-------------------:|:-----|
| Petstore | 19 | 60% | **75%** | **정확도 +15pp**, 토큰 70% 절감 |
| GitHub | 50 | 20% | 20% | 동일 정확도, **토큰 60% 절감** |
| **Kubernetes** | **248** | **실행 불가** | **60%** | 248개 tool = 10만 토큰. 소형 모델 context에 안 들어감. **검색 없이는 아예 불가능.** |

핵심: tool 수가 늘어날수록 전체를 LLM에 넣는 방식은 한계에 부딪힙니다. **248개 tool**이면 모델이 받을 수조차 없습니다 — graph-tool-call이 5개로 필터링해서 비로소 **60% 정확도**를 달성합니다.

### 검색은 얼마나 정확한가?

LLM이 보기 전에, graph-tool-call이 먼저 올바른 tool을 **찾아야** 합니다. **Recall@K**로 측정합니다: *"정답 tool이 상위 K개 결과에 포함되는가?"*

| API | 전체 tool 수 | Recall@3 | Recall@5 | Recall@10 |
|-----|:----------:|:--------:|:--------:|:---------:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub REST | 50 | 77.5% | **85.0%** | 87.5% |
| MCP (filesystem + GitHub) | 38 | 90.0% | **96.7%** | 100.0% |
| Kubernetes | 248 | 60.0% | **64.0%** | 72.0% |

19개 tool일 때 정답이 top-5에 포함될 확률 **98%**. 248개에서도 **Recall@10 = 72%** — 임베딩 모델 없이 BM25 + 그래프 탐색만으로 달성한 수치입니다.

<details>
<summary>작업 유형별 상세 분석</summary>

**Petstore** (19 tools) — Recall@5

| 작업 유형 | Recall | 쿼리 수 |
|----------|:------:|:------:|
| read | 100.0% | 8 |
| write | 100.0% | 8 |
| delete | 100.0% | 3 |
| workflow (다중 tool) | 66.7% | 1 |

**GitHub** (50 tools) — Recall@5

| 작업 유형 | Recall | 쿼리 수 |
|----------|:------:|:------:|
| write | 94.1% | 17 |
| read | 80.0% | 20 |
| delete | 66.7% | 3 |

**Kubernetes** (248 tools) — Recall@5

| 작업 유형 | Recall | 쿼리 수 |
|----------|:------:|:------:|
| write | 80.0% | 15 |
| delete | 75.0% | 8 |
| read | 51.9% | 27 |

</details>

### 임베딩은 언제 도움이 되는가?

BM25 + 그래프 위에 임베딩 모델을 추가한 결과 — **tool 수**와 **모델 품질**에 따라 효과가 달랐습니다.

**Qwen3-Embedding-0.6B** (Ollama):

| API | Tool 수 | BM25 + Graph | + 임베딩 | 변화 | 개선 | 저하 |
|-----|:------:|:------------:|:-------:|:----:|:----:|:----:|
| Petstore | 19 | 98.3% | 98.3% | — | 0 | 0 |
| MCP | 38 | 96.7% | 96.7% | — | 0 | 0 |
| GitHub | 58 | 85.0% | 80.0% | -5pp | 0 | 2 |
| **Kubernetes** | **248** | **64.0%** | **68.0%** | **+4pp** | **2** | **0** |

**패턴**: 소/중 규모에서는 BM25 키워드 매칭이 이미 충분히 정확합니다 — tool 이름이 쿼리 키워드와 직접 매칭되는 경우(예: "look up user" → `getUser`) 임베딩이 오히려 방해됩니다. 반면 **대규모(248개 이상)**에서는 비슷한 이름의 tool이 많아(`readCoreV1NamespacedPodStatus` vs `connectCoreV1GetNamespacedPodAttach`) BM25만으로 구별이 안 되고, 임베딩의 시맨틱 이해가 진가를 발휘합니다.

<details>
<summary>모델 품질이 중요합니다</summary>

같은 테스트를 nomic-embed-text로 돌리면 결과가 더 나쁩니다 — 저하가 더 많고, 개선은 더 적습니다:

| API | Tool 수 | nomic-embed-text | Qwen3-Embedding-0.6B |
|-----|:------:|:----------------:|:--------------------:|
| MCP | 38 | 90.0% (↓2) | **96.7%** (↓0) |
| GitHub | 58 | 77.5% (↓3) | **80.0%** (↓2) |
| K8s | 248 | 66.0% (↑1) | **68.0%** (↑2) |

좋은 임베딩 모델 = 소규모에서 노이즈 감소 + 대규모에서 더 큰 개선.

</details>

**권장**: tool 수가 ~100개를 넘으면 임베딩 활성화. 그 이하에서는 BM25 + 그래프만으로 충분합니다. 임베딩을 활성화한다면 고품질 모델을 사용하세요 — 측정 가능한 차이가 납니다.

### 직접 재현하기

```bash
# 검색 품질 측정 (빠름, LLM 불필요)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v          # Kubernetes 248 tools

# LLM 포함 E2E 테스트
python -m benchmarks.run_benchmark --mode e2e -m qwen3:4b

# 임베딩 비교
python -m benchmarks.run_embedding_benchmark --embedding "ollama/nomic-embed-text"
```

## 설치

```bash
pip install graph-tool-call                    # core (BM25 + graph)
pip install graph-tool-call[embedding]         # + 임베딩, cross-encoder reranker
pip install graph-tool-call[openapi]           # + OpenAPI YAML 지원
pip install graph-tool-call[all]               # 전부
```

<details>
<summary>모든 extras</summary>

```bash
pip install graph-tool-call[lint]              # + ai-api-lint spec 자동 수정
pip install graph-tool-call[similarity]        # + rapidfuzz 중복 탐지
pip install graph-tool-call[visualization]     # + pyvis HTML 그래프 내보내기
pip install graph-tool-call[langchain]         # + LangChain tool 어댑터
```

</details>

## 빠른 시작

### 30초 예제

```python
from graph_tool_call import ToolGraph

# 공식 Petstore API에서 tool graph 생성
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",  # 로컬 저장 → 다음 로드 시 즉시 사용
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# tool 검색 — 이 스펙 기준 Recall@5 98.3%
tools = tg.retrieve("새 펫을 등록", top_k=5)
for t in tools:
    print(f"  {t.name}: {t.description}")
# → addPet: Add a new pet to the store.
#   updatePet: Update an existing pet.
#   getPetById: Find pet by ID.
#   ...그래프 확장이 전체 CRUD 워크플로우를 가져옴
```

### Swagger / OpenAPI에서 생성

```python
from graph_tool_call import ToolGraph

# 파일에서 (JSON/YAML)
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# URL에서 — Swagger UI의 모든 spec 그룹 자동 탐색
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# 캐싱 — 한 번 빌드, 즉시 재사용
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",  # 첫 호출: fetch + build + save
)                          # 이후: 파일에서 로드 (네트워크 불필요)

# 지원: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
```

### MCP 서버 Tool에서 생성

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

# Annotation-aware: "파일 삭제" → destructive 도구 상위 랭크
tools = tg.retrieve("임시 파일 삭제", top_k=5)
```

MCP annotation (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)이 검색 신호로 활용됩니다. query intent가 자동 분류되어 tool annotation과 매칭 — 조회 쿼리는 read-only를, 삭제 쿼리는 destructive를 우선합니다.

### Python 함수에서 생성

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """파일 내용을 읽는다."""

def write_file(path: str, content: str) -> None:
    """파일에 내용을 쓴다."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# type hint에서 파라미터, docstring에서 설명 자동 추출
```

### 수동 Tool 등록

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# OpenAI function-calling 포맷 — 자동 감지
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

# 관계 수동 정의
tg.add_relation("get_weather", "get_forecast", "complementary")
```

## 임베딩 (하이브리드 검색)

BM25 + 그래프 위에 임베딩 기반 시맨틱 검색 추가. OpenAI-호환 endpoint라면 어디든 사용 가능.

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers (로컬, API 키 불필요)
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / OpenAI-호환 서버
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")  # URL@model 포맷

# 커스텀 callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

임베딩 활성화 시 가중치가 자동 재조정됩니다. 직접 튜닝도 가능:

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

## 저장 & 로드

한 번 빌드하면 어디서든 재사용. 전체 그래프 구조(노드, 엣지, 관계 타입, 가중치)가 보존됩니다.

```python
# 저장
tg.save("my_graph.json")

# 로드
tg = ToolGraph.load("my_graph.json")

# from_url()에서 cache= 옵션으로 자동 저장/로드
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

## 고급 기능

### Cross-Encoder 리랭킹

Cross-encoder 모델로 2차 리랭킹. `(query, tool_description)` 쌍을 함께 인코딩하여 독립 임베딩 비교보다 정확한 스코어링.

```python
tg.enable_reranker()  # 기본: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("주문 취소", top_k=5)
# wRRF로 먼저 랭킹 → cross-encoder로 재스코어링
```

### MMR 다양성

Maximal Marginal Relevance 리랭킹으로 중복 결과 감소.

```python
tg.enable_diversity(lambda_=0.7)  # 0.7 = 관련성 위주 + 약간의 다양성
```

### History-Aware 검색

이전에 호출한 tool 이름을 전달하면 컨텍스트가 개선됩니다. 이미 사용한 tool은 하향, 그래프 이웃이 시드로 확장.

```python
# 첫 호출
tools = tg.retrieve("주문 찾기")
# → [listOrders, getOrder, ...]

# 두 번째 호출 — history-aware
tools = tg.retrieve("이제 취소해줘", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
#    listOrders/getOrder 하향, cancelOrder 그래프 근접성으로 상향
```

### wRRF 가중치 튜닝

각 스코어링 소스의 weighted Reciprocal Rank Fusion 가중치 조정:

```python
tg.set_weights(
    keyword=0.2,     # BM25 텍스트 매칭
    graph=0.5,       # 그래프 탐색 (관계 기반)
    embedding=0.3,   # 시맨틱 유사도
    annotation=0.2,  # MCP annotation 매칭
)
```

### LLM 강화 온톨로지

LLM으로 더 풍부한 tool 온톨로지 구축. 카테고리, 관계 추론, 검색 키워드 생성 (비영어 tool 설명에 특히 유용).

```python
# 아래 모두 사용 가능 — wrap_llm()이 자동 감지
tg.auto_organize(llm="ollama/qwen2.5:7b")           # 문자열 shorthand
tg.auto_organize(llm=lambda p: my_llm(p))            # callable
tg.auto_organize(llm=openai.OpenAI())                # OpenAI 클라이언트
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")    # litellm 경유
```

<details>
<summary>지원하는 LLM 입력</summary>

| 입력 | 래핑 타입 |
|------|----------|
| `OntologyLLM` 인스턴스 | 그대로 사용 |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAI 클라이언트 (`chat.completions` 보유) | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completion 래퍼 |

</details>

### 중복 탐지

여러 API spec에서 중복 tool 탐지 및 병합:

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### 내보내기 & 시각화

```python
# 인터랙티브 HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (Gephi, yEd용)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint 통합

[ai-api-lint](https://github.com/SonAIengine/ai-api-lint)로 수집 전 OpenAPI spec 자동 수정:

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)  # 수집 중 자동 수정
```

## 왜 벡터 검색만으로는 부족한가?

| 시나리오 | 벡터만 사용 | graph-tool-call |
|----------|-----------|-----------------|
| *"주문 취소해줘"* | `cancelOrder` 반환 | `listOrders → getOrder → cancelOrder → processRefund` (전체 워크플로우) |
| *"파일 읽고 저장"* | `read_file` 반환 | `read_file` + `write_file` (COMPLEMENTARY 관계) |
| *"오래된 레코드 삭제"* | "삭제"와 매칭되는 아무 도구 | destructive 도구 우선 랭크 (annotation-aware) |
| *"이제 취소해줘"* (history) | 컨텍스트 없음, 동일 결과 | 사용한 tool 하향, 다음 단계 tool 상향 |
| 여러 Swagger spec에 중복 tool | 결과에 중복 포함 | cross-source 자동 중복 제거 |
| 1,200개 API endpoint | 느리고 노이즈 많음 | 카테고리로 조직화, 정확한 그래프 탐색 |

## 전체 API 레퍼런스

<details>
<summary>ToolGraph 메서드</summary>

| 메서드 | 설명 |
|--------|------|
| `add_tool(tool)` | 단일 tool 추가 (포맷 자동 감지) |
| `add_tools(tools)` | 여러 tool 추가 |
| `ingest_openapi(source)` | OpenAPI/Swagger spec에서 수집 |
| `ingest_mcp_tools(tools)` | MCP tool list에서 수집 |
| `ingest_functions(fns)` | Python callable에서 수집 |
| `ingest_arazzo(source)` | Arazzo 1.0.0 워크플로우 spec 수집 |
| `from_url(url, cache=...)` | Swagger UI 또는 spec URL에서 빌드 |
| `add_relation(src, tgt, type)` | 수동 관계 추가 |
| `auto_organize(llm=...)` | tool 자동 분류 |
| `build_ontology(llm=...)` | 전체 온톨로지 빌드 |
| `retrieve(query, top_k=10)` | tool 검색 |
| `enable_embedding(provider)` | 하이브리드 임베딩 검색 활성화 |
| `enable_reranker(model)` | cross-encoder 리랭킹 활성화 |
| `enable_diversity(lambda_)` | MMR 다양성 활성화 |
| `set_weights(...)` | wRRF 융합 가중치 튜닝 |
| `find_duplicates(threshold)` | 중복 tool 탐지 |
| `merge_duplicates(pairs)` | 탐지된 중복 병합 |
| `apply_conflicts()` | CONFLICTS_WITH 엣지 감지/추가 |
| `save(path)` / `load(path)` | 직렬화 / 역직렬화 |
| `export_html(path)` | 인터랙티브 HTML 시각화 내보내기 |
| `export_graphml(path)` | GraphML 포맷 내보내기 |
| `export_cypher(path)` | Neo4j Cypher 문장 내보내기 |

</details>

## 기능 비교

| 기능 | 벡터만 사용하는 솔루션 | graph-tool-call |
|------|---------------------|-----------------|
| Tool 소스 | 수동 등록 | Swagger/OpenAPI/MCP 자동 수집 |
| 검색 방식 | 단순 벡터 유사도 | 다단계 하이브리드 (wRRF + rerank + MMR) |
| 행동적 의미 | 없음 | MCP annotation-aware retrieval |
| Tool 관계 | 없음 | 6가지 관계 타입, 자동 감지 |
| 호출 순서 | 없음 | 상태 머신 + CRUD + response→request 데이터 플로우 |
| 중복 제거 | 없음 | Cross-source 중복 탐지 |
| 온톨로지 | 없음 | Auto / LLM-Auto 모드 (아무 LLM) |
| History | 없음 | 사용한 tool 하향, 다음 단계 상향 |
| Spec 품질 | 좋은 spec 가정 | ai-api-lint 자동 수정 통합 |
| LLM 의존성 | 필수 | 선택 (없어도 동작, 있으면 더 좋음) |

## 문서

| 문서 | 설명 |
|------|------|
| [아키텍처](docs/architecture/overview.md) | 시스템 개요, 파이프라인 레이어, 데이터 모델 |
| [WBS](docs/wbs/) | Work Breakdown Structure — Phase 0~4 진행 상황 |
| [설계](docs/design/) | 알고리즘 설계 — spec 정규화, 의존성 감지, 검색 모드, 호출 순서, 온톨로지 모드 |
| [리서치](docs/research/) | 경쟁 분석, API 규모 데이터, 커머스 패턴 |
| [OpenAPI 가이드](docs/design/openapi-guide.md) | 더 좋은 tool graph를 만드는 API spec 작성법 |

## 기여하기

기여를 환영합니다!

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

## 라이선스

[MIT](LICENSE)
