# graph-tool-call v2 — Tool Lifecycle Management for LLM Agents

## 핵심 재정의

graph-tool-call은 "그래프 retrieval 엔진"이 아니라 **Tool Lifecycle Management 라이브러리**다.

```
기존 생태계의 문제:
━━━━━━━━━━━━━━━━━

1. Swagger 200개 endpoint → 어떻게 tool로 만들지?    → 변환은 있지만 flat list일 뿐
2. 여러 API/MCP server → tool이 500개              → 중복 감지/제거 솔루션 없음
3. tool 간 의존관계 (auth → query → write)          → 자동 감지 거의 없음
4. 어떤 tool을 줄까? → 벡터 유사도만                → 관계/맥락 무시

graph-tool-call이 해결하는 것:
━━━━━━━━━━━━━━━━━━━━━━━━━━━

OpenAPI/MCP/코드 → [수집] → [분석] → [조직화] → [검색] → Agent에 전달
                    ↑         ↑        ↑          ↑
                  Ingest    Analyze   Organize   Retrieve
                  (변환)    (관계발견) (그래프)   (hybrid검색)
```

## 경쟁 구도 — 4개 프로젝트는 보완 관계

```
               검색 공간 축소 방법
               ┌──────────────────────────────────┐
               │                                  │
    RAG-MCP    │  "어떤 tool을 가져올까?"           │  → 벡터 유사도
               │  (Query-time filtering)           │
               │                                  │
    LAPIS      │  "tool을 어떻게 표현할까?"         │  → 포맷 압축 (85% 토큰 감소)
               │  (Representation optimization)    │
               │                                  │
 graph-tool-   │  "tool 간 관계를 어떻게 활용할까?" │  → 구조적 탐색
    call       │  (Structure-aware traversal)      │
               │                                  │
 langgraph-    │  "누가 retrieval을 결정할까?"      │  → LLM 자기결정
   bigtool     │  (Agent-driven retrieval)         │
               └──────────────────────────────────┘
```

**이 4개는 경쟁이 아니라 레이어:**
- LAPIS 포맷으로 압축 → graph-tool-call로 관계 기반 검색 → bigtool agent loop에서 사용
- graph-tool-call의 `retrieve()`를 bigtool의 `retrieve_tools_function`에 플러그인

**우리만의 차별점**: 4개 중 **tool 간 관계를 명시적으로 모델링하는 프로젝트는 graph-tool-call뿐**.
RAG-MCP, bigtool 모두 각 tool을 독립 벡터로 취급.

## 실제 API 규모 데이터 (리서치 결과)

설계 결정에 반영할 실측 데이터:

| API | Endpoints | Schemas | Tags | 추정 토큰 | File Size |
|-----|-----------|---------|------|----------|-----------|
| Petstore | 20 | 10 | 3 | ~15K | 35KB |
| Slack | 174 | 48 | 0 (없음) | ~120K | 1.18MB |
| Stripe | 587 | 1,335 | 0 (없음!) | ~997K | 3.8MB |
| Kubernetes | 1,085 | 746 | 64 | ~740K | 3.74MB |
| GitHub | 1,079 | 911 | 45 | ~1,672K | 11.31MB |

**핵심 인사이트:**
- 평균 API는 **~51 endpoints** (200K 파일 분석 결과)
- Stripe, GitHub 같은 대형 API는 **어떤 LLM context에도 raw로 들어가지 않음**
- **Stripe는 tag가 전혀 없음** → 자동 categorization 필수
- 가장 큰 request body: 60개 필드 (Stripe payment_methods)
- `anyOf` 1,910회 (Stripe) → polymorphic type 처리 필요
- 분산 전략 사례: Twilio (54개 파일로 분리)

**설계 반영:**
1. Ingest 시 spec 전체를 메모리에 올리지 않고 streaming/incremental 파싱
2. Tag 없는 spec 대응: path prefix + HTTP method 기반 자동 categorization
3. 대형 request body: required 필드만 tool parameter로 노출하는 옵션

## Dependency Detection — 알고리즘 상세 설계

### 학술 근거

RESTler (Microsoft, ICSE 2019)의 producer-consumer inference를 참고하되 단순화:

```
RESTler 3-Tier 매칭:
  Tier 1: 사용자 annotation (수동)
  Tier 2: Exact name match (response field → parameter)
  Tier 3: Fuzzy match (naming convention 정규화)

우리 접근 (Layer 기반, confidence score 부여):
  Layer 1: Structural (높은 확신) — path hierarchy, CRUD pattern, $ref 공유
  Layer 2: Name-based (중간 확신) — exact match, suffix/prefix, naming convention
  Layer 3: Semantic (낮은 확신) — embedding similarity (Phase 2)
```

### 구체적 알고리즘

```python
def detect_dependencies(spec, tools):
    relations = []

    # --- Layer 1: Structural (확신도 높음) ---

    # 1a. Path hierarchy → parent-child
    # /users/{userId}/orders → users가 orders의 parent
    for tool in tools:
        parent_path = truncate_at_last_param(tool.metadata["path"])
        parent_tool = find_tool_by_path(tools, parent_path, method="POST")
        if parent_tool:
            relations.append((parent_tool, tool, REQUIRES, confidence=0.95))

    # 1b. CRUD pattern (same base path, different methods)
    path_groups = group_by_base_path(tools)
    for group in path_groups:
        create = find_by_method(group, "POST")
        read = find_by_method(group, "GET", has_path_param=True)
        update = find_by_method(group, "PUT") or find_by_method(group, "PATCH")
        delete = find_by_method(group, "DELETE")
        list_op = find_by_method(group, "GET", has_path_param=False)

        if create and read:
            relations.append((create, read, REQUIRES, 0.95))
        if create and update:
            relations.append((create, update, COMPLEMENTARY, 0.9))
        if read and list_op:
            relations.append((read, list_op, SIMILAR_TO, 0.85))
        if update and delete:
            relations.append((update, delete, CONFLICTS_WITH, 0.8))

    # 1c. Shared $ref schema
    for tool_a, tool_b in combinations(tools, 2):
        shared = shared_schema_refs(tool_a, tool_b, spec)
        if shared:
            relations.append((tool_a, tool_b, COMPLEMENTARY, 0.85))

    # --- Layer 2: Name-based (확신도 중간) ---

    # 2a. Response field → Parameter name matching
    for tool_a in tools:
        output_fields = extract_response_fields(tool_a)
        for tool_b in tools:
            if tool_a == tool_b:
                continue
            input_params = extract_input_params(tool_b)
            for out_field in output_fields:
                for in_param in input_params:
                    if exact_or_suffix_match(out_field, in_param):
                        relations.append((tool_a, tool_b, REQUIRES, 0.75))
                        break

    return relations

def exact_or_suffix_match(field_a, field_b):
    """RESTler의 naming convention 정규화 적용."""
    # normalize: camelCase, snake_case, kebab-case → 토큰 리스트
    tokens_a = normalize_name(field_a)  # "userId" → ["user", "id"]
    tokens_b = normalize_name(field_b)  # "user_id" → ["user", "id"]
    return tokens_a == tokens_b or tokens_a[-1:] == tokens_b[-1:]  # suffix match
```

### False Positive 대응

RESTler/RestTestGen 연구에서 밝혀진 주요 false positive 패턴:

| 패턴 | 예시 | 대응 |
|------|------|------|
| Generic field name | `id`, `name`, `type`이 무관한 endpoint 간 매칭 | **container name 포함 매칭**: `user.id` → `userId` (O), `product.id` → `userId` (X) |
| Type mismatch | string `id` → integer `petId` | **type 일치 검증 추가** |
| Circular dependency | POST A → POST B → POST A | **cycle detection (DFS)** |
| Same-endpoint self-ref | GET /users response에 `id`, GET /users의 query에 `id` | **self-reference 제외** |

### 정확도 예상 (RESTler 연구 기반)

- Layer 1 (Structural): **Precision ~95%, Recall ~60%** — 확실하지만 놓치는 것 있음
- Layer 2 (Name-based): **Precision ~75%, Recall ~85%** — 더 많이 찾지만 오탐 있음
- Layer 1+2 결합: **Precision ~80%, Recall ~85%** — 실용적 수준

## Deduplication — 알고리즘 상세 설계

### 5단계 파이프라인

```
Stage 1: Exact Hash         → SHA256(canonical(name + params))     O(n)
Stage 2: Name Fuzzy Match   → RapidFuzz Jaro-Winkler > 0.85       O(n²) but fast (C++)
Stage 3: Schema Structural  → Parameter key Jaccard + type compat  O(n² * params)
Stage 4: Semantic Desc      → Sentence embedding cosine > 0.85     O(n² * embed_dim)
Stage 5: Composite Score    → 0.2*name + 0.3*schema + 0.5*semantic
   → > 0.85: auto-merge
   → 0.70-0.85: flag for review
   → < 0.70: not duplicate
```

### 라이브러리 선택 근거

**RapidFuzz** (MIT, C++ 구현):
- 2,500 pairs/sec (difflib의 2.5배)
- Jaro-Winkler: 짧은 tool name에 최적 (prefix 유사 보너스)
- token_sort_ratio: 단어 순서 무관 비교 ("get user" vs "user get")
- `process.cdist()`: 대규모 batch 유사도 matrix 생성

### Merge 전략

```python
class MergeStrategy(Enum):
    KEEP_FIRST = "keep_first"     # 먼저 등록된 것 유지
    KEEP_BEST = "keep_best"       # description 길이 + param docs 완성도 기준
    CREATE_ALIAS = "create_alias" # canonical + alias 관계 유지
```

## Retrieval — Hybrid Engine 상세 설계

### 현재 문제점과 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| "파일 읽기" → read_file 매칭 실패 | token exact match | Embedding semantic similarity |
| tags 있으면 TypeError | `set.update(generator of lists)` | `for t in tags: tokens.update(tokenize(t))` |
| keyword weight 30%로 과소평가 | 경험적 설정 | 적응적 가중치 (query 특성 기반) |
| embedding 미구현 | Phase 2로 미루어놓음 | Phase 1에서 바로 구현 |

### Hybrid 검색 파이프라인 (개선)

```
Query: "사용자 파일을 읽고 DB에 저장해줘"
  │
  ├─ [1] BM25-style Keyword Score
  │   tokenize + TF-IDF weighting
  │   → read_file: 0.42, write_file: 0.15, query_db: 0.38, ...
  │
  ├─ [2] Embedding Cosine Score (optional)
  │   all-MiniLM-L6-v2 (384d, 22.7M params)
  │   → read_file: 0.78, write_file: 0.31, save_to_db: 0.72, ...
  │
  ├─ [3] Graph Expansion Score
  │   Top-5 seeds from [1]+[2] → BFS(max_depth=2)
  │   relation weight × distance decay
  │   → write_file: 0.7 (COMPLEMENTARY of read_file)
  │   → list_dir: 0.5 (REQUIRES of read_file)
  │
  └─ [4] Score Fusion (RRF — Reciprocal Rank Fusion)
      RRF가 score scale 차이에 robust (BM25 vs cosine vs graph)
      final = Σ 1/(k + rank_i) for each scoring method
      → Top-K 반환
```

### 왜 RRF인가?

리서치 결과 (BEIR benchmark):
- BM25 only: NDCG@10 = 43.4
- Dense only: NDCG@10 = ~45
- **Hybrid BM25+Dense+RRF: NDCG@10 > 52.6** (+20% 이상)
- Recall: 0.72 (BM25) → **0.91 (Hybrid)**

단순 가중합보다 RRF가 scale 차이에 강건하고, 추가 hyperparameter 튜닝이 적음.

### Workflow Coverage — 고유 평가 지표

graph-tool-call만의 강점을 측정하는 metric:

> "파일을 읽고 수정해서 저장하라" → read_file, write_file **모두** retrieve 되어야 함

벡터만으로는 write_file을 놓칠 수 있지만, COMPLEMENTARY 관계를 통해 자동으로 포함.

## 아키텍처 (v2)

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

## 사용자 경험 (목표 API)

### 1. Swagger → 조직화된 Tool Graph (핵심 시나리오)

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Swagger/OpenAPI spec에서 tool 자동 생성 + 관계 자동 발견
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# → 20개 endpoint → 20개 ToolSchema
# → CRUD 패턴 인식: POST /pet → GET /pet/{petId} (REQUIRES)
# → 같은 tag "pet" → "pet" 카테고리 자동 생성
# → path hierarchy: /pet/{petId}/uploadImage → REQUIRES addPet

print(tg)
# ToolGraph(tools=20, categories=3, relations=34)

# 쿼리 기반 검색
tools = tg.retrieve("새 펫을 등록하고 사진을 업로드해줘", top_k=5)
# → [addPet, uploadFile, getPetById, updatePet, findPetsByStatus]
```

### 2. 여러 소스 통합 + Deduplication

```python
tg = ToolGraph()
tg.ingest_openapi("./user-service-swagger.json")
tg.ingest_openapi("./order-service-swagger.json")
tg.add_tools(langchain_custom_tools)

# 중복 감지
dupes = tg.find_duplicates(threshold=0.85)
# → [("user_service.get_user", "order_service.fetch_user", 0.92)]
tg.merge_duplicates(dupes, strategy="keep_best")
```

### 3. bigtool의 retrieval backend

```python
from langgraph_bigtool import create_agent
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("./api-spec.json")

def retrieve_tools(query: str) -> list[str]:
    return [t.name for t in tg.retrieve(query, top_k=5)]

builder = create_agent(llm, tool_registry, retrieve_tools_function=retrieve_tools)
```

### 4. Standalone

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.add_tools(openai_function_tools)
tg.add_relation("read_file", "write_file", "complementary")
tg.save("my_tools.json")
```

## 프로젝트 구조 (v2)

```
graph-tool-call/
├── pyproject.toml
├── graph_tool_call/
│   ├── __init__.py                    # ToolGraph public API
│   ├── tool_graph.py                  # ToolGraph facade
│   │
│   ├── core/                          # 핵심 데이터 모델
│   │   ├── protocol.py                # GraphEngine Protocol
│   │   ├── graph.py                   # NetworkX 구현
│   │   └── tool.py                    # ToolSchema + 포맷 파서
│   │
│   ├── ingest/                        # 수집/변환 레이어
│   │   ├── openapi.py                 # OpenAPI/Swagger → ToolSchema[]
│   │   ├── mcp.py                     # MCP server → ToolSchema[] (Phase 3)
│   │   └── functions.py               # Python callable → ToolSchema
│   │
│   ├── analyze/                       # 분석 레이어
│   │   ├── dependency.py              # 3-layer dependency detection
│   │   ├── similarity.py              # 5-stage deduplication pipeline
│   │   └── conflict.py                # 충돌 관계 감지
│   │
│   ├── ontology/                      # 조직화 레이어
│   │   ├── schema.py                  # RelationType, NodeType
│   │   ├── builder.py                 # 수동 온톨로지 빌더
│   │   └── auto.py                    # LLM/embedding 기반 자동 조직화
│   │
│   ├── retrieval/                     # 검색 레이어
│   │   ├── engine.py                  # Hybrid retrieval + RRF fusion
│   │   ├── graph_search.py            # 그래프 탐색 (BFS)
│   │   ├── keyword.py                 # BM25-style keyword scoring
│   │   └── embedding.py              # 임베딩 유사도
│   │
│   ├── integrations/                  # 통합 레이어
│   │   ├── langchain.py               # LangChain BaseRetriever
│   │   └── bigtool.py                 # bigtool retrieve_tools adapter
│   │
│   └── serialization.py              # 그래프 저장/로드
│
├── tests/
├── examples/
│   ├── quickstart.py
│   ├── swagger_to_agent.py
│   ├── multi_api_dedup.py
│   └── bigtool_plugin.py
├── README.md
└── LICENSE (MIT)
```

## 개발 Phase

### Phase 1: Ingest + Dependency + Retrieval 개선 (2주)

기존 구현 위에 바로 쌓는다.

**1-1. 버그 수정 (Day 1)**
- tags 처리 TypeError 수정
- keyword matching: BM25-style TF-IDF scoring으로 교체

**1-2. `ingest/openapi.py` (Day 2-5)**
- OpenAPI 3.0/3.1 + Swagger 2.0 파싱 (jsonschema $ref resolution)
- operation → ToolSchema 변환 (name, description, parameters)
- 대형 request body 처리: required 필드만 노출 옵션
- deprecated endpoint 필터링

**1-3. `analyze/dependency.py` (Day 6-8)**
- Layer 1: path hierarchy + CRUD pattern + $ref 공유 (구조적)
- Layer 2: response field → parameter name matching (이름 기반)
- naming convention 정규화 (camelCase ↔ snake_case ↔ kebab-case)
- confidence score 부여 + cycle detection

**1-4. `ingest/functions.py` (Day 9)**
- Python callable → ToolSchema (inspect.signature 기반)
- docstring → description 추출

**1-5. Retrieval 개선 (Day 10)**
- `retrieval/keyword.py`: BM25-style scoring 구현
- `retrieval/engine.py`: RRF score fusion으로 교체
- tags 기반 scoring 통합

**1-6. 테스트 + 예제 (Day 11-14)**
- Petstore swagger end-to-end 테스트
- `examples/swagger_to_agent.py` 예제

**Phase 1 완료 기준:**
```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
assert tg.graph.has_edge("addPet", "getPetById")  # CRUD dependency
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
assert "addPet" in [t.name for t in tools]
assert "uploadFile" in [t.name for t in tools]
```

### Phase 2: Deduplication + Embedding + Auto-organize (2주)

**2-1. `analyze/similarity.py` (Day 1-4)**
- 5-stage deduplication pipeline
- RapidFuzz Jaro-Winkler (이름) + TF-IDF cosine (설명) + Jaccard (파라미터)
- `tg.find_duplicates()`, `tg.merge_duplicates()`

**2-2. `retrieval/embedding.py` (Day 5-7)**
- sentence-transformers all-MiniLM-L6-v2 (22.7M params, 384d)
- EmbeddingIndex에 실제 검색 통합
- `RetrievalEngine`에 embedding score 연결

**2-3. `ontology/auto.py` (Day 8-10)**
- LLM 기반 자동 온톨로지 (50개씩 batch)
- embedding clustering 기반 fallback (LLM 없이도 동작)

**2-4. `integrations/bigtool.py` (Day 11-12)**
- bigtool retrieve_tools_function adapter
- 예제: `examples/bigtool_plugin.py`

**2-5. 벤치마크 (Day 13-14)**
- 평가 설계:
  - Tool set: Petstore (20), GitHub subset (50), Synthetic (500)
  - Query set: single-tool, multi-tool, workflow
  - Metrics: Precision@K, Recall@K, NDCG@K, **Workflow Coverage**
  - Baselines: all-tools, random-k, embedding-only, graph-tool-call

**Phase 2 완료 기준:**
```python
tg.ingest_openapi("./user-api.json")
tg.ingest_openapi("./order-api.json")
dupes = tg.find_duplicates()              # cross-API 중복 감지
tg.auto_organize(llm=llm)                 # LLM 자동 관계 구성
tools = tg.retrieve("사용자 주문 조회")    # 한국어 동작 (embedding)
```

### Phase 3: MCP + Production + 배포 (2주)

1. `ingest/mcp.py`: MCP server tool 수집
2. `analyze/conflict.py`: 충돌 관계 감지 강화
3. CLI: `graph-tool-call ingest spec.json -o graph.json`
4. 그래프 시각화 (HTML export)
5. GitHub Actions CI + PyPI 배포
6. README + 사용 가이드

### Phase 4: 커뮤니티 + 최적화

1. PyPI 정식 배포
2. LangChain community package 등록
3. bigtool 연동 PR
4. 블로그: "Why Graph > Vector for Tool Retrieval"
5. (선택) LAPIS 포맷 출력 지원
6. (선택) Rust(PyO3+petgraph) 최적화

## 기술 스택

| 구분 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.10+ | LangChain 생태계 호환 |
| 그래프 | NetworkX | 가벼움, 충분히 빠름 |
| OpenAPI 파싱 | jsonschema + pyyaml (직접 파싱) | prance 의존성 무거움 → 경량 구현 |
| 이름 유사도 | RapidFuzz (MIT, C++) | 2,500 pairs/sec, Jaro-Winkler 최적 |
| 임베딩 | all-MiniLM-L6-v2 (optional) | 22.7M params, 384d, 가장 실용적 |
| Score fusion | RRF (Reciprocal Rank Fusion) | Scale-agnostic, hyperparameter 적음 |
| 빌드 | Poetry | LangChain 컨벤션 |
| 테스트 | pytest | 표준 |
| 포맷 | ruff | 빠름 |

## 의존성 전략

```toml
[tool.poetry.dependencies]
# Core (minimal)
python = "^3.10"
networkx = "^3.0"
pydantic = "^2.0"

[tool.poetry.extras]
# pip install graph-tool-call[openapi]
openapi = ["pyyaml", "jsonschema"]
# pip install graph-tool-call[embedding]
embedding = ["numpy", "sentence-transformers"]
# pip install graph-tool-call[similarity]
similarity = ["rapidfuzz"]
# pip install graph-tool-call[langchain]
langchain = ["langchain-core"]
# pip install graph-tool-call[all]
all = ["pyyaml", "jsonschema", "numpy", "rapidfuzz", "langchain-core"]

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
ruff = "^0.8"
```

## 성공 기준

### 정량적
- Petstore (20 endpoints) → tool graph 생성 + dependency 감지 precision 80%+
- 500-tool set에서 bigtool(벡터만) 대비 **Workflow Coverage 20%+ 개선**
- Retrieval latency: 100ms 이내 (500 tools, CPU)
- Deduplication: 0.85 threshold에서 precision 90%+

### 정성적
- `tg.ingest_openapi(url)` 한 줄로 Swagger → 관계 포함 tool graph
- bigtool 연동 3줄
- LangChain 없이 standalone 동작

### 학술적 차별점
- Tool 간 관계를 모델링하는 유일한 오픈소스 retrieval 엔진
- Workflow Coverage: multi-step 작업에서의 tool 완전성 평가 metric 제안

## 리스크와 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| OpenAPI 파싱 edge case (anyOf, $ref 순환) | Ingest 실패 | 보수적 파싱 + graceful fallback |
| Dependency false positive 많음 | 신뢰도 저하 | confidence score + threshold 조정 |
| Embedding 의존성 무거움 | 설치 장벽 | strict optional, embedding 없이도 동작 |
| 대형 spec (1000+ endpoints) 성능 | 느린 분석 | incremental 처리, O(n²) → batch 최적화 |
| auto_organize LLM 비용 | 사용 장벽 | embedding clustering fallback (LLM 불필요) |

## 참고 문헌

### Dependency Detection
- RESTler: Stateful REST API Fuzzing (ICSE 2019, Microsoft)
- RestTestGen: Operation Dependency Graph (ICST 2020)
- KAT: LLM-based Dependency Inference (ICST 2024)
- AutoRestTest: SPDG + GloVe + MARL (ICSE 2025)

### Deduplication
- SynthTools: Tool ecosystem deduplication (arXiv:2511.09572)
- SemDeDup: Semantic deduplication at scale (arXiv:2303.09540, Meta)
- JSONGlue: Hybrid JSON schema matching (SBBD 2020)

### Retrieval
- RAG-MCP: Vector-based tool retrieval (arXiv:2505.03275)
- LAPIS: 85% token reduction format (arXiv:2602.18541)
- ToolLLM: Trained Sentence-BERT for API retrieval (arXiv:2307.16789)
- BEIR: Hybrid BM25+Dense+RRF benchmark

### Tool Scaling
- MCP SEP-1576: Token bloat mitigation
- MCP Discussion #532: Hierarchical tool management
