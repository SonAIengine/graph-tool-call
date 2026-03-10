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

## 왜 벡터 검색만으로는 부족한가?

| 시나리오 | 벡터만 사용 | graph-tool-call |
|----------|-----------|-----------------|
| *"주문 취소해줘"* | `cancelOrder` 반환 | `listOrders → getOrder → cancelOrder → processRefund` (전체 워크플로우) |
| *"파일 읽고 저장"* | `read_file` 반환 | `read_file` + `write_file` (COMPLEMENTARY 관계) |
| *"오래된 레코드 삭제"* | "삭제"와 매칭되는 아무 도구 | destructive 도구 우선 랭크 (annotation-aware) |
| *"이제 취소해줘"* (history) | 컨텍스트 없음, 동일 결과 | 사용한 tool 하향, 다음 단계 tool 상향 |
| 여러 Swagger spec에 중복 tool | 결과에 중복 포함 | cross-source 자동 중복 제거 |
| 1,200개 API endpoint | 느리고 노이즈 많음 | 카테고리로 조직화, 정확한 그래프 탐색 |

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

## 벤치마크

graph-tool-call이 실제로 LLM의 tool 선택을 도와주는지 테스트했습니다.

1. LLM에게 사용자 요청을 줌 (예: *"default 네임스페이스의 모든 pod를 조회해줘"*)
2. tool 정의 목록을 함께 제공
3. LLM이 정답 tool을 고르는지 확인

두 가지를 측정했습니다:

| 지표 | 무엇을 측정하나 | 예시 |
|------|---------------|------|
| **정확도 (Accuracy)** | LLM이 정답 tool을 골랐는가? | "pod 목록 조회" → LLM이 `listCoreV1NamespacedPod` 선택 → 정답 |
| **Recall@K** | 정답 tool이 후보 목록에 들어있었는가? | `listCoreV1NamespacedPod`가 상위 5개에 포함 → 포함됨 |

> **둘 다 중요한 이유**: 정답 tool이 후보에 없으면 (낮은 Recall) LLM이 아무리 똑똑해도 고를 수 없습니다. 후보에 있는데 LLM이 다른 걸 고르면 (낮은 Accuracy) 그건 검색이 아니라 LLM 선택의 문제입니다.

### 핵심 발견: tool이 너무 많으면 LLM이 혼란에 빠진다

| API | Tool 수 | 방식 | 정확도 | Recall@5 |
|-----|:------:|------|:------:|:--------:|
| Petstore | 19 | graph-tool-call 없이 (19개 전부) | 100% | — |
| GitHub | 50 | graph-tool-call 없이 (50개 전부) | 100% | — |
| MCP Servers | 38 | graph-tool-call 없이 (38개 전부) | 96.7% | — |
| **Kubernetes** | **248** | **graph-tool-call 없이 (248개 전부)** | **12%** | — |
| | | **graph-tool-call 사용 (상위 5개 선별)** | **78%** | **91%** |
| | | + 임베딩 | **80%** | **94%** |
| | | + 온톨로지 | **82%** | **96%** |
| | | + 둘 다 | **82%** | **98%** |

**Kubernetes에서 무슨 일이?**
- **Baseline (248개 전부 전달)**: LLM이 248개 tool을 한꺼번에 봅니다. 너무 많아서 혼란에 빠지고, 88%를 틀림 → **정확도 12%**. (Recall은 기술적으로 100% — 정답이 목록에 *있긴* 하지만, LLM이 찾지 못하는 것.)
- **graph-tool-call 사용**: 관련성 높은 5개로 필터링. LLM이 **78–82%** 정답률 달성. 최적화가 아니라 **쓸 수 있느냐 없느냐의 차이**.

**50개 미만**: LLM이 잘 처리함. graph-tool-call은 **64–88% 토큰 절감** 효과 (더 빠르고, 더 저렴).

> 모델: qwen3:4b (4-bit 양자화, Ollama). 데이터셋당 50개 테스트 쿼리. 모든 스펙은 공개 — [직접 재현 가능](#직접-재현하기).

<details>
<summary>데이터셋별 전체 결과</summary>

**Petstore** (19 tools, 20 쿼리)

| Pipeline | 정확도 | Recall@K | 평균 토큰 | 토큰 절감 |
|----------|:------:|:--------:|:--------:|:--------:|
| baseline (전체 tool) | 100.0% | 100.0% | 1,239 | — |
| retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |

**GitHub** (50 tools, 40 쿼리)

| Pipeline | 정확도 | Recall@K | 평균 토큰 | 토큰 절감 |
|----------|:------:|:--------:|:--------:|:--------:|
| baseline (전체 tool) | 100.0% | 100.0% | 3,302 | — |
| retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |

**Mixed MCP** (38 tools, 30 쿼리)

| Pipeline | 정확도 | Recall@K | 평균 토큰 | 토큰 절감 |
|----------|:------:|:--------:|:--------:|:--------:|
| baseline (전체 tool) | 96.7% | 100.0% | 2,741 | — |
| retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |

**Kubernetes core/v1** (248 tools, 50 쿼리)

| Pipeline | 정확도 | Recall@K | 평균 토큰 | 토큰 절감 |
|----------|:------:|:--------:|:--------:|:--------:|
| baseline (전체 tool) | 12.0% | 100.0% | 8,192 | — |
| retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| + 임베딩 | 80.0% | 94.0% | 1,728 | 78.9% |
| + 온톨로지 | **82.0%** | 96.0% | 1,699 | 79.3% |
| + 둘 다 | **82.0%** | **98.0%** | 1,924 | 76.5% |

</details>

### 임베딩 + 온톨로지는 언제 도움이 되는가?

소규모 API(50개 미만)에서는 BM25 + 그래프 탐색만으로 충분합니다. 대규모 API에서는 임베딩과 온톨로지가 실질적인 차이를 만듭니다. Kubernetes (248 tools)에서 테스트:

| Pipeline | 정확도 | Recall@5 | 추가되는 기능 |
|----------|:------:|:--------:|-------------|
| BM25 + 그래프만 | 78% | 91% | 키워드 매칭 + 그래프 이웃 탐색 |
| + 임베딩 | 80% | 94% | 의미적 유사도 (BM25가 놓치는 동의어 포착) |
| + 온톨로지 | **82%** | 96% | LLM이 생성한 키워드 + example queries |
| **+ 둘 다** | **82%** | **98%** | 임베딩 + 온톨로지가 상호 보완 |

임베딩: OpenAI `text-embedding-3-small`. 온톨로지: `gpt-4o-mini`.

### 직접 재현하기

```bash
# 검색 품질 측정 (빠름, LLM 불필요)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# 전체 파이프라인 벤치마크 (Ollama 필요)
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# 베이스라인 저장 후 변경사항 비교
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

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
