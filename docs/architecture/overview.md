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
사용자 코드 / LangChain / LangGraph
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
│  │     Call ordering detection (PRECEDES)       │  │
│  │     Deduplication (5-stage pipeline)         │  │
│  │     CRUD pattern recognition                 │  │
│  │     State machine detection                  │  │
│  │     Conflict detection                       │  │
│  └──────────────┬──────────────────────────────┘  │
│                 │                                  │
│  ┌──────────────▼──────────────────────────────┐  │
│  │  3. ORGANIZE (조직화) — Auto / LLM-Auto       │  │
│  │     Auto: tag/path/CRUD/embedding clustering │  │
│  │     LLM-Auto: + LLM 관계 추론/카테고리 제안  │  │
│  │     Ontology graph 구축 (NetworkX)           │  │
│  │     Domain → Category → Tool 계층            │  │
│  └──────────────┬──────────────────────────────┘  │
│                 │                                  │
│  ┌──────────────▼──────────────────────────────┐  │
│  │  4. RETRIEVE (검색) — 3-Tier + Annotation     │  │
│  │     Tier 0: BM25 + graph + annotation (0LLM)│  │
│  │     Tier 1: + query expansion (Small LLM)   │  │
│  │     Tier 2: + intent decomposition (Full)   │  │
│  │     4-source wRRF fusion → Top-K             │  │
│  │     Intent classifier → Annotation scorer   │  │
│  └─────────────────────────────────────────────┘  │
│                                                   │
│  ┌─────────────────────────────────────────────┐  │
│  │  5. INTEGRATE (통합)                         │  │
│  │     MCP Server (stdio/sse transport)        │  │
│  │     MCP Proxy (aggregate + filter backends) │  │
│  │     SDK Middleware (OpenAI/Anthropic patch)  │  │
│  │     CLI (search/serve/proxy/ingest/retrieve)│  │
│  │     LangChain BaseRetriever                  │  │
│  │     Standalone Python API                    │  │
│  │     Serialization (JSON 저장/로드)           │  │
│  │     Dashboard (시각화 + 수동 편집)           │  │
│  └─────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
graph_tool_call/
├── __init__.py                    # ToolGraph public API
├── __main__.py                    # CLI (search/serve/ingest/retrieve/...)
├── tool_graph.py                  # ToolGraph facade
├── mcp_server.py                  # MCP 서버 (FastMCP 기반 tool provider)
├── mcp_proxy.py                   # MCP 프록시 (다중 백엔드 집계 + 필터링)
├── middleware.py                   # SDK middleware (OpenAI/Anthropic auto-filter)
├── serialization.py               # 그래프 저장/로드
│
├── core/                          # 핵심 데이터 모델
│   ├── protocol.py                # GraphEngine Protocol
│   ├── graph.py                   # NetworkX 구현
│   └── tool.py                    # MCPAnnotations + ToolSchema + 포맷 파서
│
├── ingest/                        # 수집/변환 레이어
│   ├── openapi.py                 # OpenAPI/Swagger → ToolSchema[] (annotation 자동 추론)
│   ├── normalizer.py              # Swagger 2.0/3.0/3.1 정규화
│   ├── mcp.py                     # MCP tool list → ToolSchema[] (annotations 보존)
│   ├── arazzo.py                  # Arazzo 1.0.0 워크플로우 파서
│   └── functions.py               # Python callable → ToolSchema
│
├── analyze/                       # 분석 레이어
│   ├── dependency.py              # 3-layer dependency + ordering detection
│   ├── similarity.py              # 5-stage deduplication pipeline
│   └── conflict.py                # 충돌 관계 감지
│
├── ontology/                      # 조직화 레이어
│   ├── schema.py                  # RelationType, NodeType
│   ├── builder.py                 # 온톨로지 빌더
│   ├── auto.py                    # Auto/LLM-Auto 조직화
│   └── llm_provider.py            # OntologyLLM (Ollama/vLLM/OpenAI)
│
├── retrieval/                     # 검색 레이어
│   ├── engine.py                  # 4-source wRRF retrieval (BM25+Graph+Embedding+Annotation)
│   ├── intent.py                  # QueryIntent + classify_intent() (한/영 zero-LLM)
│   ├── annotation_scorer.py       # Intent↔Annotation alignment scoring
│   ├── graph_search.py            # 그래프 탐색 (BFS)
│   ├── keyword.py                 # BM25-style keyword scoring
│   ├── embedding.py               # 임베딩 유사도
│   ├── search_llm.py              # SearchLLM (Tier 1/2 query expansion)
│   └── model_driven.py            # Model-Driven Search API
│
├── visualization/                 # 시각화 레이어
│   ├── html_export.py             # Pyvis HTML export
│   └── neo4j_export.py            # Neo4j Cypher export
│
└── integrations/                  # 통합 레이어
    └── langchain.py               # LangChain BaseRetriever
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

**이들은 경쟁이 아니라 보완 관계:**
- LAPIS 포맷으로 압축 → graph-tool-call로 관계 기반 검색 → Agent에서 사용
- graph-tool-call은 독립 라이브러리로 운영 (외부 프레임워크 의존 없음)

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
[mcp]: + mcp (MCP SDK)
[all]: 전부
```
