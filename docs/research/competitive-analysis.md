# 경쟁 생태계 분석

## 4개 프로젝트 비교

| 차원 | RAG-MCP | bigtool | LAPIS | graph-tool-call |
|------|---------|---------|-------|-----------------|
| 접근 | 벡터 필터링 | LLM 자기결정 | 포맷 압축 | 구조적 탐색 |
| Tool 관계 | 없음 | 없음 | Flow 선언(정적) | 5종 RelationType(동적) |
| Token 절약 | ~50% | 동적 바인딩 | ~85% | 관계 기반 정밀 선택 |
| LLM 의존 | Embedding만 | 높음 | 없음 | 없음 (auto만 LLM) |

## langgraph-bigtool

- GitHub: langchain-ai/langgraph-bigtool (517 stars, 2025.03~)
- 핵심: "tool을 검색하는 tool" 하나만 LLM에 제공
- 실제 코드 ~200줄, LangGraph Store의 벡터 검색에 위임
- `retrieve_tools_function` 파라미터로 커스텀 retrieval 주입 가능 → **우리의 플러그인 포인트**
- tool 간 관계: 전혀 고려하지 않음
- selected_tool_ids가 누적만 됨 (제거 메커니즘 없음)

## RAG-MCP

- 논문: arXiv:2505.03275
- all-MiniLM-L6-v2 (384d) 임베딩, brute-force cosine similarity
- 결과: prompt token 49% 감소, accuracy 3.17x 향상 (13.62% → 43.13%)
- 한계: tool 간 관계 미고려, ~100개 tool 이후 precision 저하

## LAPIS

- 논문: arXiv:2602.18541
- OpenAPI YAML 대비 85.5% 토큰 감소
- 7개 섹션: meta, types, ops, errors, flows, auth, examples
- `[flows]` 섹션이 operation 간 dependency를 선언적으로 표현

## OpenAPI → Tool 변환 기존 솔루션

### Python
| 패키지 | Stars | 특징 |
|--------|-------|------|
| openapi-llm (vblagoje) | 42 | OpenAPI → LLM tool defs + API 호출 |
| LangChain OpenAPIToolkit | - | Planner/Controller 패턴, 복잡 |

### OpenAPI → MCP Server
| 도구 | 특징 |
|------|------|
| FastMCP.from_openapi() | tag-based filtering, custom route map |
| openapi-to-mcp (PyPI) | v2/v3, auth forwarding |
| Speakeasy | dynamic mode, 50+ production 경험 |

### 우리 차별점
기존 도구들은 **flat list 변환**만 함. 우리는 변환과 동시에 **관계 추출**:
- 같은 path CRUD → REQUIRES/COMPLEMENTARY
- response → parameter 매칭 → REQUIRES
- 같은 tag → category (BELONGS_TO)
