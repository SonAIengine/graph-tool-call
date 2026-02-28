<div align="center">

# graph-tool-call

**LLM Agent를 위한 Tool Lifecycle Management**

수집, 분석, 조직화, 검색.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · 한국어 · [中文](README-zh_CN.md) · [日本語](README-ja.md)

</div>

---

## 문제

LLM Agent가 사용할 수 있는 tool이 점점 많아지고 있습니다. 커머스 플랫폼은 **1,200개 이상의 API endpoint**를 가지고 있고, 회사 내부 시스템은 여러 서비스에 걸쳐 **500개 이상의 함수**를 가질 수 있습니다.

하지만 한계가 있습니다: **모든 tool을 context window에 넣을 수 없습니다.**

일반적인 해결책은 벡터 검색입니다 — tool 설명을 임베딩하고, 가장 가까운 것을 찾습니다. 동작은 하지만, 중요한 것을 놓칩니다:

> **Tool은 독립적으로 존재하지 않습니다. 서로 관계가 있습니다.**

사용자가 *"주문을 취소하고 환불 처리해줘"*라고 말하면, 벡터 검색은 `cancelOrder`를 찾을 수 있습니다. 하지만 주문 ID를 얻기 위해 먼저 `listOrders`를 호출해야 하고, 이후에 `processRefund`가 와야 한다는 것은 모릅니다. 이것들은 단순히 비슷한 tool이 아닙니다 — **워크플로우**를 이루고 있습니다.

## 해결책

**graph-tool-call**은 tool 간 관계를 그래프로 모델링합니다:

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

각 tool을 독립적인 벡터로 취급하는 대신, graph-tool-call은 이해합니다:
- **REQUIRES** — `getOrder`는 `listOrders`의 ID가 필요함
- **PRECEDES** — 주문 목록을 조회해야 취소할 수 있음
- **COMPLEMENTARY** — 취소와 환불은 함께 사용됨
- **SIMILAR_TO** — `getOrder`와 `listOrders`는 관련된 기능
- **CONFLICTS_WITH** — `updateOrder`와 `deleteOrder`는 동시 실행 불가

*"주문 취소"*를 검색하면, `cancelOrder`만 나오는 것이 아니라 **전체 워크플로우**가 나옵니다: 목록 조회 → 상세 조회 → 취소 → 환불.

## 동작 방식

```
OpenAPI/MCP/코드 → [수집] → [분석] → [조직화] → [검색] → Agent
                    (변환)  (관계발견) (그래프)   (hybrid)
```

**1. 수집(Ingest)** — Swagger spec, MCP 서버, Python 함수를 가리키면 됩니다. tool이 통합 스키마로 자동 변환됩니다.

**2. 분석(Analyze)** — 관계가 자동으로 감지됩니다: path 계층, CRUD 패턴, 공유 스키마, response-parameter 체인, 상태 머신.

**3. 조직화(Organize)** — tool이 온톨로지 그래프로 그룹핑됩니다. 두 가지 모드:
  - **Auto** — 순수 알고리즘 (tag, path, CRUD 패턴). LLM 불필요.
  - **LLM-Auto** — LLM 추론으로 강화 (Ollama, vLLM, OpenAI). 더 나은 카테고리, 풍부한 관계.

**4. 검색(Retrieve)** — 키워드 매칭, 그래프 탐색, (선택적) 임베딩을 결합한 하이브리드 검색. LLM 없이도 잘 동작합니다. LLM이 있으면 더 좋아집니다.

## 빠른 시작

```bash
pip install graph-tool-call
```

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Tool 등록 (OpenAI / Anthropic / LangChain 포맷 자동 감지)
tg.add_tools(your_tools_list)

# 관계 정의
tg.add_relation("read_file", "write_file", "complementary")

# 검색 — 그래프 확장이 관련 tool을 자동으로 찾음
tools = tg.retrieve("파일을 읽고 변경사항을 저장", top_k=5)
# → [read_file, write_file, list_dir, ...]
#    write_file는 벡터 유사도가 아닌 COMPLEMENTARY 관계로 발견됨
```

### Swagger / OpenAPI에서 자동 생성

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
# 지원: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
# 입력: 파일 경로 (JSON/YAML), URL, 또는 raw dict

# 자동 처리: 5개 endpoint → 5개 tool → CRUD 관계 → 카테고리
# 의존성, 호출 순서, 카테고리 그룹핑 — 모두 자동 감지.

tools = tg.retrieve("새 펫을 등록", top_k=5)
# → [createPet, getPet, updatePet, listPets, deletePet]
#    그래프 확장이 전체 CRUD 워크플로우를 가져옴
```

### Python 함수에서 자동 생성

```python
def read_file(path: str) -> str:
    """파일 내용을 읽는다."""

def write_file(path: str, content: str) -> None:
    """파일에 내용을 쓴다."""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# type hint에서 파라미터 추출, docstring에서 설명 추출
```

## 왜 벡터 검색만으로는 부족한가?

| 시나리오 | 벡터만 사용 | graph-tool-call |
|----------|-----------|-----------------|
| *"주문 취소해줘"* | `cancelOrder` 반환 | `listOrders → getOrder → cancelOrder → processRefund` (전체 워크플로우) |
| *"파일 읽고 저장"* | `read_file` 반환 | `read_file` + `write_file` (COMPLEMENTARY 관계) |
| 여러 Swagger spec에 중복 tool | 결과에 중복 포함 | cross-source 자동 중복 제거 |
| 1,200개 API endpoint | 느리고 노이즈 많음 | 카테고리로 조직화, 정확한 그래프 탐색 |

## 3-Tier 검색: 가진 것만 사용하세요

graph-tool-call은 **LLM 없이도 동작**하고, **있으면 더 좋아지도록** 설계되었습니다:

| Tier | 필요한 것 | 하는 일 | 개선 효과 |
|------|----------|---------|----------|
| **0** | 아무것도 필요 없음 | BM25 키워드 + 그래프 확장 + RRF 융합 | 기본 |
| **1** | 소형 LLM (1.5B~3B) | + 쿼리 확장, 동의어, 번역 | Recall +15~25% |
| **2** | 대형 LLM (7B+) | + 의도 분해, 반복 정제 | Recall +30~40% |

Ollama에서 실행되는 작은 모델(`qwen2.5:1.5b`)만으로도 검색 품질이 의미 있게 향상됩니다. Tier 0은 GPU도 필요 없습니다.

## 기능 비교

| 기능 | 벡터만 사용하는 솔루션 | graph-tool-call |
|------|---------------------|-----------------|
| Tool 소스 | 수동 등록 | Swagger/OpenAPI/MCP 자동 수집 |
| 검색 방식 | 단순 벡터 유사도 | 그래프 + 벡터 하이브리드 (RRF), 3-Tier |
| Tool 관계 | 없음 | 6가지 관계 타입, 자동 감지 |
| 호출 순서 | 없음 | 상태 머신 + CRUD 워크플로우 감지 |
| 중복 제거 | 없음 | Cross-source 중복 감지 |
| 온톨로지 | 없음 | Auto / LLM-Auto 모드 |
| 시각화 | 없음 | 그래프 대시보드 + 수동 편집 |
| LLM 의존성 | 필수 | 선택 (없어도 동작, 있으면 더 좋음) |

## 로드맵

| Phase | 내용 | 상태 |
|-------|------|------|
| **0** | 핵심 그래프 엔진 + 하이브리드 검색 | ✅ 완료 (39 tests) |
| **1** | OpenAPI 수집, BM25+RRF 검색, 의존성 감지 | ✅ 완료 (88 tests) |
| **2** | 중복 제거, 임베딩, 온톨로지 모드 (Auto/LLM-Auto), 검색 Tier | 계획됨 |
| **3** | MCP 수집, Pyvis 시각화, Neo4j export, CLI, PyPI 배포 | 계획됨 |
| **4** | Interactive Dashboard (Dash Cytoscape), 수동 편집, 커뮤니티 | 계획됨 |

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
```

## 라이선스

[MIT](LICENSE)
