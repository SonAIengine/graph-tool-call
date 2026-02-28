# Research Notes — graph-tool-call

리서치 결과를 주제별로 정리한 문서. PLAN.md의 설계 결정 근거.

## 1. 경쟁 생태계 분석

### langgraph-bigtool

- GitHub: langchain-ai/langgraph-bigtool (517 stars, 2025.03~)
- 핵심: "tool을 검색하는 tool" 하나만 LLM에 제공, LLM이 자기결정으로 retrieval
- 실제 코드 ~200줄, LangGraph Store의 벡터 검색에 위임
- `retrieve_tools_function` 파라미터로 커스텀 retrieval 주입 가능 → **우리의 플러그인 포인트**
- tool 간 관계: 전혀 고려하지 않음
- selected_tool_ids가 누적만 됨 (제거 메커니즘 없음)

### RAG-MCP

- 논문: arXiv:2505.03275
- all-MiniLM-L6-v2 (384d) 임베딩, brute-force cosine similarity
- 결과: prompt token 49% 감소, accuracy 3.17x 향상 (13.62% → 43.13%)
- 한계: tool 간 관계 전혀 미고려, ~100개 tool 이후 precision 저하
- **우리와 보완 관계**: RAG-MCP의 embedding을 seed 선정에 활용 가능

### LAPIS

- 논문: arXiv:2602.18541
- OpenAPI YAML 대비 85.5% 토큰 감소
- 7개 섹션: meta, types, ops, errors, flows, auth, examples
- `[flows]` 섹션이 operation 간 dependency를 선언적으로 표현 (우리 REQUIRES와 유사)
- **우리와 보완 관계**: retrieved tool을 LAPIS 포맷으로 압축하여 LLM에 전달

### 4개 프로젝트 차원 비교

| 차원 | RAG-MCP | bigtool | LAPIS | graph-tool-call |
|------|---------|---------|-------|-----------------|
| 접근 | 벡터 필터링 | LLM 자기결정 | 포맷 압축 | 구조적 탐색 |
| Tool 관계 | 없음 | 없음 | Flow 선언(정적) | 5종 RelationType(동적) |
| Token 절약 | ~50% | 동적 바인딩 | ~85% | 관계 기반 정밀 선택 |
| LLM 의존 | Embedding만 | 높음 | 없음 | 없음 (auto만 LLM) |

## 2. 실제 API Spec 규모 데이터

### 주요 API 실측

| API | File Size | Endpoints | Schemas | Tags | Deprecated |
|-----|-----------|-----------|---------|------|------------|
| GitHub REST | 11.31 MB | 1,079 | 911 | 45 | 31 (2.9%) |
| Kubernetes | 3.74 MB | 1,085 | 746 | 64 | 0 |
| Stripe | 3.80 MB | 587 | 1,335 | **0 (없음!)** | 6 |
| Slack | 1.18 MB | 174 | 48 | 0 | 0 |
| Twilio | 10.44 MB | ~1,000+ | ~800+ | 분산(54파일) | N/A |

### APIs.guru 통계

- 총 API: 3,992개 (고유 2,529개)
- 총 endpoint: 108,837개
- **평균: ~43 endpoints/API**
- 200K 파일 분석 평균: ~51 endpoints, ~33 schemas, ~38 query params

### Context Window 초과 문제

| Spec | 추정 토큰 | Claude 200K 대비 |
|------|----------|-----------------|
| Slack (174 ep) | ~120K | 60% (겨우 들어감) |
| Kubernetes (1,085 ep) | ~740K | **370%** (불가) |
| Stripe (587 ep) | ~997K | **499%** (불가) |
| GitHub (1,079 ep) | ~1,672K | **836%** (불가) |

### 설계에 반영할 인사이트

1. **Stripe는 tag가 없음** → path prefix 기반 자동 categorization 필수
2. Stripe `anyOf` 1,910회 → polymorphic type 처리 필요
3. 가장 큰 request body: 60개 필드 → required만 노출 옵션
4. 가장 큰 schema: 105개 properties (GitHub `full-repository`)
5. Twilio 분산 전략 (54개 파일) → incremental ingest 지원
6. 27% API에 보안 전략 없음 → auth 처리 robust해야

## 3. Dependency Detection 알고리즘

### 학술 논문 계보

| 논문 | 연도 | 핵심 기여 |
|------|------|-----------|
| RESTler (Microsoft) | ICSE 2019 | Producer-consumer inference 최초 체계화 |
| RestTestGen | ICST 2020 | Operation Dependency Graph (ODG) |
| Morest | ICSE 2022 | RESTful-service Property Graph + 동적 피드백 |
| KAT | ICST 2024 | LLM(GPT-3.5) 기반 semantic dependency |
| AutoRestTest | ICSE 2025 | GloVe + MARL + SPDG |

### RESTler 알고리즘 요약

3-Tier 매칭:
1. Annotation 기반 (사용자 수동 지정)
2. Exact name match (response field name → parameter name)
3. Fuzzy match (naming convention 정규화: camelCase ↔ snake_case)

Producer 제한: POST/PUT만 (GET은 선택적)
Naming convention 지원: CamelCase, PascalCase, HyphenSeparator, UnderscoreSeparator

### 우리 접근 (RESTler 단순화)

```
Layer 1 (Structural, precision ~95%, recall ~60%):
  - Path hierarchy: /users/{id}/orders → parent-child
  - CRUD pattern: same base path + different HTTP method
  - $ref schema 공유

Layer 2 (Name-based, precision ~75%, recall ~85%):
  - Response field → parameter name matching
  - Naming convention 정규화
  - Container + field concatenation (user.id → userId)

Layer 3 (Semantic, Phase 2):
  - Embedding similarity
  - LLM reasoning
```

### False Positive 패턴

| 패턴 | 대응 |
|------|------|
| Generic field (`id`, `name`, `type`) | container name 포함 매칭 |
| Type mismatch | type 일치 검증 |
| Circular dependency | DFS cycle detection |
| Self-reference | same-endpoint 제외 |

## 4. Deduplication 기법

### 학술 근거

- **SynthTools** (arXiv:2511.09572): 5,900 tool 중 9% near-duplicate 감지
- **SemDeDup** (Meta, arXiv:2303.09540): K-means + pairwise cosine, 50% 데이터 제거해도 성능 유지
- **JSONGlue** (SBBD 2020): Linguistic + Semantic + Instance-based 3종 matcher 병렬

### 유사도 Metric 비교

| Metric | F1 | Recall | 최적 용도 |
|--------|-----|--------|----------|
| Jaro-Winkler | **1.0** | 1.0 | 짧은 이름, typo |
| Levenshtein | **1.0** | 1.0 | literal match |
| TF-IDF Cosine | **0.95** | ~0.95 | semantic 포함 |
| Jaccard | ~0.60 | 0.40 | paraphrase 실패 |

### 라이브러리 비교

| 라이브러리 | 속도 (pairs/sec) | 라이선스 |
|-----------|-----------------|---------|
| **RapidFuzz** | **2,500** | **MIT** |
| python-Levenshtein | 1,800 | GPL |
| FuzzyWuzzy | 1,200 | GPL |
| difflib | 1,000 | stdlib |

결론: **RapidFuzz** 선택 (MIT, 최고 속도, FuzzyWuzzy superset)

### Retrieval Hybrid 효과 (BEIR benchmark)

| 방법 | NDCG@10 | Recall |
|------|---------|--------|
| BM25 only | 43.4 | 0.72 |
| Dense only | ~45 | - |
| **Hybrid BM25+Dense+RRF** | **>52.6** | **0.91** |

RRF (Reciprocal Rank Fusion):
- `score = Σ 1/(k + rank_i)` for each scoring method
- Score scale 차이에 robust (BM25 점수 vs cosine 점수)
- Hyperparameter: k만 (보통 60)

## 5. OpenAPI → Tool 변환 기존 솔루션

### Python

| 패키지 | Stars | 특징 |
|--------|-------|------|
| openapi-llm (vblagoje) | 42 | OpenAPI → LLM tool defs + API 호출 |
| LangChain OpenAPIToolkit | - | Planner/Controller 패턴, 복잡 |

### TypeScript

| 패키지 | 특징 |
|--------|------|
| @samchon/openapi | Swagger 2.0/3.0/3.1, multi-provider 출력 |
| Agentica (@wrtnlabs) | samchon 기반, compiler-driven |

### OpenAPI → MCP Server

| 도구 | 특징 |
|------|------|
| FastMCP.from_openapi() | tag-based filtering, custom route map |
| openapi-to-mcp (PyPI) | v2/v3, auth forwarding |
| Speakeasy | dynamic mode, 50+ production 경험 |
| AWS OpenAPI MCP Server | 공식, 동적 tool/resource 생성 |

### 우리 차별점

기존 도구들은 **flat list 변환**만 함. 우리는 변환과 동시에 **관계 추출**:
- 같은 path CRUD → REQUIRES/COMPLEMENTARY
- response → parameter 매칭 → REQUIRES
- 같은 tag → category (BELONGS_TO)

## Sources

### 논문
- RESTler: Stateful REST API Fuzzing (ICSE 2019) — https://patricegodefroid.github.io/public_psfiles/icse2019.pdf
- RestTestGen (ICST 2020) — https://profs.scienze.univr.it/~ceccato/papers/2020/icst2020api.pdf
- KAT (ICST 2024) — https://arxiv.org/html/2407.10227v1
- AutoRestTest (ICSE 2025) — https://arxiv.org/abs/2411.07098
- RAG-MCP — https://arxiv.org/html/2505.03275v1
- LAPIS — https://arxiv.org/abs/2602.18541
- SynthTools — https://arxiv.org/html/2511.09572
- SemDeDup — https://arxiv.org/abs/2303.09540
- ToolLLM — https://ar5iv.labs.arxiv.org/html/2307.16789

### GitHub
- RESTler — https://github.com/microsoft/restler-fuzzer
- RestTestGen — https://github.com/SeUniVr/RestTestGen
- RAG-MCP — https://github.com/fintools-ai/rag-mcp
- LAPIS — https://github.com/cr0hn/LAPIS
- MetaMCP — https://github.com/metatool-ai/metamcp

### 커뮤니티
- MCP SEP-1576: Token Bloat — https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576
- MCP Discussion #532: Hierarchical Tools — https://github.com/orgs/modelcontextprotocol/discussions/532
- MCP Discussion #590: Tool Overlap — https://github.com/orgs/modelcontextprotocol/discussions/590

### 데이터
- APIs.guru — https://apis.guru
- 200K OpenAPI 분석 — https://nordicapis.com/analyzing-trends-across-200000-openapi-files/
- Stripe OpenAPI — https://github.com/stripe/openapi
- GitHub REST API — https://github.com/github/rest-api-description
