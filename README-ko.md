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

Agent가 수백~수천 개의 tool을 가지고 있을 때, 모든 tool을 context window에 넣으면 성능이 저하됩니다. 기존 솔루션들은 벡터 유사도만 사용합니다. **graph-tool-call**은 tool 간 **관계**(의존성, 호출 순서, 보완, 충돌)를 그래프로 모델링하여 구조 인식 검색을 가능하게 합니다.

```
OpenAPI/MCP/코드 → [수집] → [분석] → [조직화] → [검색] → Agent
                    (변환)  (관계발견) (그래프)   (hybrid)
```

## 왜 graph-tool-call인가?

| 기능 | 벡터만 사용하는 솔루션 | graph-tool-call |
|------|---------------------|-----------------|
| 범위 | Tool 검색만 | 전체 Tool 라이프사이클 |
| Tool 소스 | 수동 등록 | Swagger/OpenAPI 자동 수집 |
| 검색 | 단순 벡터 유사도 | 그래프 + 벡터 하이브리드 (RRF), 3-Tier |
| 관계 | 없음 | REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH |
| 중복 제거 | 없음 | Cross-source 중복 감지 |
| 의존성 | 없음 | API spec에서 자동 감지 |
| 호출 순서 | 없음 | 상태 머신 + CRUD 워크플로우 감지 |
| 온톨로지 | 없음 | Auto / LLM-Auto 모드 |

## 빠른 시작

### 설치

```bash
pip install graph-tool-call
```

### 기본 사용법

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Tool 등록 (OpenAI / Anthropic / LangChain 포맷 자동 감지)
tg.add_tools(your_tools_list)

# 카테고리와 관계 설정
tg.add_category("file_ops", domain="io")
tg.assign_category("read_file", "file_ops")
tg.add_relation("read_file", "write_file", "complementary")

# 쿼리로 관련 tool 검색
tools = tg.retrieve("파일을 읽고 변경사항을 저장", top_k=5)
```

### OpenAPI 수집 (Phase 1)

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# CRUD 의존성, 호출 순서, 카테고리 자동 발견
tools = tg.retrieve("새 펫을 등록하고 사진을 업로드", top_k=5)
```

## 주요 기능

### 수집 (Ingest)
OpenAPI/Swagger, MCP 서버, Python 함수, LangChain/OpenAI/Anthropic 포맷의 tool을 통합 스키마로 자동 변환합니다. Swagger 2.0, OpenAPI 3.0, 3.1 버전 차이를 Spec Normalization으로 투명하게 처리합니다.

### 분석 (Analyze)
Tool 간 관계를 자동 감지합니다:
- **REQUIRES** — 데이터 의존 (response → parameter)
- **PRECEDES** — 호출 순서 (목록 조회 → 취소)
- **COMPLEMENTARY** — 함께 사용하면 유용 (read ↔ write)
- **SIMILAR_TO** — 유사한 기능
- **CONFLICTS_WITH** — 동시 실행 시 충돌

### 조직화 (Organize)
두 가지 모드로 온톨로지 그래프를 구축합니다:
- **Auto** — 알고리즘 기반 카테고리 분류 (tag, path, CRUD 패턴, embedding clustering). LLM 불필요.
- **LLM-Auto** — Auto + LLM으로 관계 추론 및 카테고리 제안 강화 (Ollama, vLLM, llama.cpp, OpenAI).

어떤 모드든 결과를 Dashboard에서 시각화하고 수동 편집할 수 있습니다.

### 검색 (Retrieve)
3-Tier 하이브리드 검색 아키텍처:
| Tier | LLM 필요 | 방식 |
|------|---------|------|
| 0 | 불필요 | BM25 + 그래프 확장 + RRF |
| 1 | 소형 (1.5B~3B) | + 쿼리 확장 |
| 2 | 대형 (7B+) | + 의도 분해 |

LLM 없이도 동작합니다. LLM이 있으면 더 좋아집니다.

## 로드맵

| Phase | 설명 | 상태 |
|-------|------|------|
| **0** | 핵심 그래프 + 검색 | ✅ 완료 (32 tests) |
| **1** | OpenAPI 수집 + 의존성/순서 감지 | 진행 중 |
| **2** | 중복 제거 + 임베딩 + 온톨로지/검색 모드 | 계획됨 |
| **3** | MCP 수집 + 시각화 + CLI + PyPI | 계획됨 |
| **4** | Interactive Dashboard + 커뮤니티 | 계획됨 |

## 문서

- [WBS](docs/wbs/) — Work Breakdown Structure
- [아키텍처](docs/architecture/overview.md) — 시스템 개요 및 데이터 모델
- [설계](docs/design/) — 알고리즘 설계 문서
- [리서치](docs/research/) — 경쟁 분석, API 규모 데이터

## 기여하기

기여를 환영합니다! 기여 가이드라인은 곧 제공됩니다.

```bash
# 개발 환경 설정
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev
poetry run pytest -v
```

## 라이선스

[MIT](LICENSE)
