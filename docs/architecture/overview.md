# Architecture Overview

## 핵심 정의

graph-tool-call은 **Tool Lifecycle Management 라이브러리**다.

```
OpenAPI/MCP/코드 → [수집] → [분석] → [조직화] → [검색] → Agent에 전달
                    ↑         ↑        ↑          ↑
                  Ingest    Analyze   Organize   Retrieve
                  (변환)    (관계발견) (그래프)   (hybrid검색)
```

## 파이프라인 레이어

```
사용자 코드 / LangChain / LangGraph / bigtool
                │
                ▼
┌──────────────────────────────────────────────────┐
│                graph-tool-call                    │
│                                                   │
│  ┌─────────────────────────────────────────────┐  │
│  │  1. INGEST (수집/변환)                       │  │
│  │     OpenAPI/Swagger → ToolSchema             │  │
│  │     MCP Server discovery → ToolSchema        │  │
│  │     Python functions → ToolSchema            │  │
│  │     LangChain/OpenAI/Anthropic tools 수용    │  │
│  └──────────────┬──────────────────────────────┘  │
│                 │                                  │
│  ┌──────────────▼──────────────────────────────┐  │
│  │  2. ANALYZE (분석)                           │  │
│  │     Dependency detection (3-layer)           │  │
│  │     Deduplication (5-stage pipeline)         │  │
│  │     CRUD pattern recognition                 │  │
│  │     Conflict detection                       │  │
│  └──────────────┬──────────────────────────────┘  │
│                 │                                  │
│  ┌──────────────▼──────────────────────────────┐  │
│  │  3. ORGANIZE (조직화)                        │  │
│  │     Auto-categorize (tag/path/LLM)           │  │
│  │     Ontology graph 구축 (NetworkX)           │  │
│  │     Domain → Category → Tool 계층            │  │
│  │     관계 edge (requires/complementary/...)   │  │
│  └──────────────┬──────────────────────────────┘  │
│                 │                                  │
│  ┌──────────────▼──────────────────────────────┐  │
│  │  4. RETRIEVE (검색)                          │  │
│  │     BM25-style keyword scoring               │  │
│  │     Graph traversal (BFS + relation weight)  │  │
│  │     Embedding similarity (optional)          │  │
│  │     RRF Score fusion → Top-K                 │  │
│  └─────────────────────────────────────────────┘  │
│                                                   │
│  ┌─────────────────────────────────────────────┐  │
│  │  5. INTEGRATE (통합)                         │  │
│  │     LangChain BaseRetriever                  │  │
│  │     bigtool retrieve_tools_function          │  │
│  │     Standalone Python API                    │  │
│  │     Serialization (JSON 저장/로드)           │  │
│  └─────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
graph_tool_call/
├── __init__.py                    # ToolGraph public API
├── tool_graph.py                  # ToolGraph facade
├── serialization.py               # 그래프 저장/로드
│
├── core/                          # 핵심 데이터 모델
│   ├── protocol.py                # GraphEngine Protocol
│   ├── graph.py                   # NetworkX 구현
│   └── tool.py                    # ToolSchema + 포맷 파서
│
├── ingest/                        # 수집/변환 레이어
│   ├── openapi.py                 # OpenAPI/Swagger → ToolSchema[]
│   ├── normalizer.py              # Swagger 2.0/3.0/3.1 정규화
│   ├── mcp.py                     # MCP server → ToolSchema[]
│   └── functions.py               # Python callable → ToolSchema
│
├── analyze/                       # 분석 레이어
│   ├── dependency.py              # 3-layer dependency detection
│   ├── similarity.py              # 5-stage deduplication pipeline
│   └── conflict.py                # 충돌 관계 감지
│
├── ontology/                      # 조직화 레이어
│   ├── schema.py                  # RelationType, NodeType
│   ├── builder.py                 # 수동 온톨로지 빌더
│   └── auto.py                    # LLM/embedding 기반 자동 조직화
│
├── retrieval/                     # 검색 레이어
│   ├── engine.py                  # Hybrid retrieval + RRF fusion
│   ├── graph_search.py            # 그래프 탐색 (BFS)
│   ├── keyword.py                 # BM25-style keyword scoring
│   └── embedding.py               # 임베딩 유사도
│
└── integrations/                  # 통합 레이어
    ├── langchain.py               # LangChain BaseRetriever
    └── bigtool.py                 # bigtool retrieve_tools adapter
```

## 경쟁 포지셔닝

```
               검색 공간 축소 방법
               ┌──────────────────────────────────┐
    RAG-MCP    │  "어떤 tool을 가져올까?"           │  → 벡터 유사도
    LAPIS      │  "tool을 어떻게 표현할까?"         │  → 포맷 압축 (85% 토큰 감소)
 graph-tool-   │  "tool 간 관계를 어떻게 활용할까?" │  → 구조적 탐색
    call       │                                  │
 langgraph-    │  "누가 retrieval을 결정할까?"      │  → LLM 자기결정
   bigtool     │                                  │
               └──────────────────────────────────┘
```

**이 4개는 경쟁이 아니라 레이어:**
- LAPIS 포맷으로 압축 → graph-tool-call로 관계 기반 검색 → bigtool agent loop에서 사용

## 기술 스택

| 구분 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.10+ | LangChain 생태계 호환 |
| 그래프 | NetworkX | 가벼움, 충분히 빠름 |
| OpenAPI 파싱 | jsonschema + pyyaml | 경량 구현 |
| 이름 유사도 | RapidFuzz (MIT, C++) | 2,500 pairs/sec |
| 임베딩 | all-MiniLM-L6-v2 (optional) | 22.7M params, 384d |
| Score fusion | RRF | Scale-agnostic |
| 빌드 | Poetry | LangChain 컨벤션 |
| 테스트 | pytest | 표준 |

## 의존성 전략

```
core:      networkx, pydantic
[openapi]: + pyyaml, jsonschema
[embedding]: + numpy, sentence-transformers
[similarity]: + rapidfuzz
[langchain]: + langchain-core
[all]: 전부
```
