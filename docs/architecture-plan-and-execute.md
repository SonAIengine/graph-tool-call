# Plan-and-Execute Architecture

> 작성: 2026-04-22, 업데이트: 2026-04-23
> 상태: 확정 (설계) / 미구현
> 범위: graph-tool-call 라이브러리 + xgen-workflow 통합

## 변경 이력

- **2026-04-23**: 설계 간소화
  - Ingest 시 embedding + Qdrant 저장 **삭제** (YAGNI). Field 이름 exact match 로 충분, cross-field synonym 은 LLM enrichment 가 해결
  - L0 에 **LLM per-tool enrichment (Pass 2)** 도입. graph-tool-call 이 이미 보유한 `OntologyLLM` 추상화 활용
  - Stage 1 retrieval 은 기존 BM25 + graph (graph-tool-call retrieval) 재사용. embedding prefilter 생략
  - Knowledge Base 가 **두 층** 으로 명확화: (A) 결정론적 파서 / (B) LLM semantic enrichment

---

## 0. 한 쪽 요약

**문제:** 현재 LLM-as-orchestrator (ReAct) 는 요청당 15 iteration × ~15KB context = **30초, 225KB 토큰**. 비용·지연·품질 모두 구조적 한계.

**해결:** **사전 지식 (graph + schemas + ingest 시 LLM 의미 주석)** 을 최대한 활용하고, runtime LLM 은 자연어 ↔ 구조 변환에만 사용하는 **5-layer 아키텍처** (L0 Knowledge Base + Stage 1~4 Runtime).

**기대 효과:**
- LLM 호출 15 → 2~3회
- Context 225KB → ~2~3KB (**~75배 감소**)
- Latency 30초 → 2~5초 (**~10배 개선**)
- 실행 단계 재현성, 감사 가능성 확보
- 확장 축 확보 (fan-out, template, interactive)

---

## 1. 설계 원칙

| # | 원칙 | 의미 |
|---|---|---|
| 1 | 사전 지식 최대 활용 | graph, schemas, embeddings 는 offline 구축 후 영속. 요청 처리 시 재계산 금지 |
| 2 | LLM 은 semantic bridge 에만 | 자연어 이해 / 의미 추출 / 자연어 생성 — 그 외 결정론 |
| 3 | 결정 가능한 것은 결정론적으로 | 매칭·순서·바인딩은 알고리즘. LLM 폴백은 **실패한 결정론의 보완** |
| 4 | 각 단계는 독립 입출력 계약 | 테스트·캐싱·디버깅·부분 교체 가능 |
| 5 | 하드코딩은 "학습된 지식" 으로 대체 | synonym → embedding cluster, verb → intent classifier |
| 6 | Failure mode 관측 가능 | 어느 stage 에서 왜 실패했는지 항상 명확해야 함 |

---

## 2. 시스템 개요

```
╔═══════════════════════════════════════════════════════════════╗
║                    OFFLINE / INGEST TIME                      ║
║  ┌─────────────────────────────────────────────────────────┐ ║
║  │ L0. KNOWLEDGE BASE                                       │ ║
║  │                                                          │ ║
║  │  Swagger → ToolSchema + Tool Embeddings +                │ ║
║  │            IO Contract + Tool Graph                      │ ║
║  │                                                          │ ║
║  │  저장: api_tool_collections.graph (JSONB)                 │ ║
║  │       api_tool_collections.embeddings (pgvector)         │ ║
║  │       api_tool_collections.io_contracts (JSONB)          │ ║
║  └─────────────────────────────────────────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════╝
                            │
                            ▼ (요청 도착)
╔═══════════════════════════════════════════════════════════════╗
║                    REQUEST TIME PIPELINE                      ║
║                                                               ║
║  requirement (자연어)                                          ║
║     │                                                         ║
║     ▼                                                         ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ STAGE 1. RETRIEVAL + TARGET SELECTION                 │    ║
║  │  (a) embedding prefilter: 108 → top-20                │    ║
║  │  (b) LLM pick: 20개 catalog → target + entities       │    ║
║  │  context: ~1KB  │  LLM: 1회                            │    ║
║  └────────────────┬─────────────────────────────────────┘    ║
║                   │                                           ║
║                   ▼                                           ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ STAGE 2. PATH SYNTHESIZER                             │    ║
║  │  (결정론) target 의 consumes → IO Contract 역추적      │    ║
║  │          → DAG 구성 + argument bindings                │    ║
║  │  context: —     │  LLM: 0회                            │    ║
║  └────────────────┬─────────────────────────────────────┘    ║
║                   │                                           ║
║         ┌─────────┴─────────┐                                 ║
║         │                   │                                 ║
║    확정 plan           모호 (2+ 경로)                          ║
║         │                   │                                 ║
║         │                   ▼                                 ║
║         │      ┌────────────────────────────────────────┐    ║
║         │      │ (조건부) DISAMBIGUATION                 │    ║
║         │      │  context: ~2KB (후보만) │ LLM: 1회       │    ║
║         │      └────────────┬───────────────────────────┘    ║
║         │                   │                                 ║
║         └───────────────────┘                                 ║
║                   │                                           ║
║                   ▼                                           ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ STAGE 3. RUNNER                                       │    ║
║  │  (결정론) DAG topological 실행                         │    ║
║  │          JsonPath 치환 + tool_executor HTTP           │    ║
║  │          step 단위 streaming event                     │    ║
║  │  context: —     │  LLM: 0회                            │    ║
║  └────────────────┬─────────────────────────────────────┘    ║
║                   │                                           ║
║                   ▼                                           ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ STAGE 4. RESPONSE SYNTHESIS                           │    ║
║  │  execution trace (요약) → 자연어 응답                   │    ║
║  │  context: ~1KB  │  LLM: 1회                            │    ║
║  └────────────────┬─────────────────────────────────────┘    ║
║                   │                                           ║
║                   ▼                                           ║
║                최종 답변                                        ║
╚═══════════════════════════════════════════════════════════════╝
```

**일반 케이스 예산:** LLM 2회, context ~2KB, 2~4초.
**모호 케이스:** LLM 3회, context ~4KB, 4~6초.

---

## 3. L0 — Knowledge Base

ingest 1회. 영속 저장. 요청 처리에서 재계산 금지.

**두 층 구조:**
- **Pass 1 — Deterministic parser**: Swagger 의 구조적 사실 (schema, HTTP, dependency) 추출. LLM 금지.
- **Pass 2 — Semantic enrichment**: Description 등을 LLM 이 읽고 의미 주석 (언제 써, 무엇을 내놓는다, 누구와 쌍을 이룬다). graph-tool-call 의 `OntologyLLM` 추상화 재사용.

### 3.1 ToolSchema (Pass 1, 기존 확장)

기존 `tools` 테이블. 추가 필드는 아래 섹션들이 채움.

| 필드 | 설명 | 출처 |
|---|---|---|
| `function_id` | 컬렉션 범위 고유 slug | 파서 |
| `function_name` | 원본 operationId | 파서 |
| `description` | summary + description + tags | 파서 |
| `api_url`, `api_method`, `api_header`, `api_body` | 실행용 | 파서 |
| `metadata` | method/path/base_url/tags/response_schema/controller/request_type/response_type | 파서 |
| `ai_metadata` | canonical_action, primary_resource, when_to_use, pairs_well_with 등 | **Pass 2 (LLM)** |

### 3.2 IO Contract (Pass 1, 결정론)

각 tool 의 **필드 수준 produces/consumes** 를 swagger schema 에서 기계적으로 추출.

**저장:** 신규 테이블 `tool_io_contracts`:
```sql
CREATE TABLE tool_io_contracts (
  tool_id          VARCHAR(100) REFERENCES tools(function_id),
  direction        VARCHAR(10)  CHECK (direction IN ('produces', 'consumes')),
  json_path        TEXT,         -- $.body.goods[*].goodsNo  (produces)
                                 -- goodsNo                   (consumes)
  field_name       VARCHAR(100), -- goodsNo
  field_type       VARCHAR(40),  -- integer, string, object
  required         BOOLEAN,      -- consumes 에 한함
  semantic_tag     VARCHAR(80)   -- Pass 2 LLM 이 채움 (빈 값 허용)
);
```

**추출 프로세스 (LLM 없음):**
```
for each tool in schemas:
  request_leaves  = walk_schema_leaves(tool.request_schema)
  response_leaves = walk_schema_leaves(tool.response_schema)
  
  for each leaf in request_leaves:
    insert consumes (field_name, type, required)
  
  for each leaf in response_leaves:
    insert produces (json_path, field_name, type)
```

**1차 매칭: exact field name + type** — 동일 swagger 내 field 이름 규약 보통 일관. 이걸로 대부분의 엣지 생성.

```python
# 결정론적 field match edge
for A in tools:
  for p in A.produces:
    for B in tools:
      if A == B: continue
      for c in B.consumes.required:
        if p.field_name == c.field_name and p.type == c.type:
          graph.add_edge(A, B, "produces_for",
                         binding={c.field_name: p.json_path})
```

### 3.3 Semantic Enrichment (Pass 2, LLM)

**목적:** Description 등의 비정형 정보를 LLM 이 해석해 의미 주석 추가. 하드코딩된 verb 사전 / synonym 테이블 **완전 대체**.

**인프라:** graph-tool-call 에 이미 있는 `OntologyLLM` 활용 ([graph_tool_call/ontology/llm_provider.py](graph_tool_call/ontology/llm_provider.py)).

**이미 제공되는 메서드:**
- `infer_relations(tools)` — LLM 기반 관계 추론
- `suggest_categories(tools)` — 카테고리 그룹핑
- `verify_relations(relations, tools)` — 휴리스틱 엣지 검증 / 거르기
- `suggest_missing(tools, existing)` — 빠진 엣지 제안
- `enrich_keywords(tools)` — BM25 향상용 키워드
- `generate_example_queries(tools)` — 임베딩 매칭용 예시 쿼리

**신규 메서드 (추가 구현):**
```python
class OntologyLLM:
    def enrich_tool_semantics(
        self, tools: list[ToolSummary], batch_size: int = 10,
    ) -> dict[str, ToolEnrichment]:
        """Per-tool 의미 주석 (action, resource, use-when, semantic tags, pairs)."""
```

**ToolEnrichment 스키마:**
```typescript
type ToolEnrichment = {
  canonical_action: "search" | "read" | "create" | "update" | "delete" | "action";
  primary_resource: string;                 // 정규화 리소스명 (예: "product")
  one_line_summary: string;                 // 한 줄 요약 (Stage 1 catalog 용)
  when_to_use: string;                      // 언제 쓰는지
  when_not_to_use?: string;                 // 쓰면 안 되는 경우
  produces_semantics: Array<{               // 의미 태깅된 produces
    semantic: string;                       // "product_id" 같은 canonical
    json_path: string;                      // 실제 경로
  }>;
  consumes_semantics: Array<{
    semantic: string;
    field: string;
  }>;
  pairs_well_with: Array<{                  // 함께 / 순서대로 쓰이는 도구들
    tool: string;
    reason: string;
  }>;
}
```

**Prompt 예시:**
```
You are annotating an API tool for a planning system.

Tool: seltSearchProduct
Summary: 상품 검색
Description: 키워드로 상품을 검색하는 API입니다. ...
HTTP: GET /v1/search/product
Request fields: [searchWord, langCd, siteNo, sort, ...]
Response fields: [$.body.goods[*].goodsNo, $.body.goods[*].goodsName, ...]

Produce JSON with:
- canonical_action (search|read|create|update|delete|action)
- primary_resource (one word like "product", "order", "user")
- one_line_summary (Korean, within 40 chars)
- when_to_use (1~2 sentences)
- produces_semantics: map internal field names to semantic ids like "product_id"
- pairs_well_with: 2~3 related tools with brief reason

Output JSON only. 
```

**저장:**
- `tools.ai_metadata` JSONB 컬럼 (전체 enrichment 덤프)
- `tool_io_contracts.semantic_tag` (produces_semantics / consumes_semantics 의 semantic 을 해당 row 에 매핑)

**재실행 조건:** swagger 변경, LLM 모델 업그레이드, 관리자 강제 재생성. 일상 요청 처리와 **분리**.

### 3.4 Tool Graph (재정의)

엣지 타입:

| 엣지 | 근거 | 신뢰도 | 용도 |
|---|---|---|---|
| `produces_for` (exact) | Pass 1 — field name + type 일치 | high | Stage 2 주 신호 |
| `produces_for` (semantic) | Pass 2 — `semantic_tag` 일치 | medium | Pass 1 이 못 잡는 교차 명명 (cross-collection 등) |
| `pairs_with` | Pass 2 — `pairs_well_with` 에서 | medium | Stage 1 catalog 힌트, Stage 2 보조 |
| `similar_to` | 구조적 (같은 controller / tag / CRUD 역할) | low | Disambiguation 후보 확장 |
| `precedes` | 구조적 (POST → GET single 등) | low | 레거시 엣지, 보조 힌트 |

**기존 하드코딩 반응성 패치 (selt, synonym clusters, *No/*Seq heuristic, search-bridge exception) 는 Pass 2 완성 시 모두 제거.** Pass 1 field exact match + Pass 2 LLM enrichment 가 그 역할을 대체.

### 3.5 Ingest 파이프라인

```python
# xgen-workflow 측
def ingest_collection(collection_id, spec_source, llm_config):
    from graph_tool_call.ontology.llm_provider import wrap_llm
    from graph_tool_call.ingest.openapi import parse_operations
    
    # Pass 1: 결정론
    schemas = parse_operations(spec_source)
    io_contracts = extract_io_contracts(schemas)          # 3.2
    graph = build_structural_edges(schemas, io_contracts) # 3.4
    
    # Pass 2: LLM (옵션)
    if llm_config.enabled:
        llm = wrap_llm(build_llm_spec(llm_config))
        enrichments = llm.enrich_tool_semantics(schemas)
        apply_semantic_tags(io_contracts, enrichments)    # semantic_tag 채움
        graph = augment_with_semantic_edges(graph, enrichments)
    
    store_all(schemas, io_contracts, graph, enrichments)
```

**옵션:** Pass 2 는 `llm_config.enabled=False` 로 **생략 가능**. Pass 1 만으로도 기본 동작은 가능 (품질은 낮음).

### 3.6 xgen-workflow 통합

xgen 은 이미 agent 노드에서 provider/model/api_key 선택 지원. Ingest 시에도 동일 config 재사용:

```python
# xgen-workflow: api_tool_collection/service.py
def refresh_with_enrichment(collection_id, llm_settings):
    llm_spec = f"{llm_settings.provider}/{llm_settings.model}"  
    # "openai/gpt-4.1-mini"
    
    # api_key 는 env 또는 xgen secret store 에서
    os.environ["OPENAI_API_KEY"] = xgen_secret.get(user_id, "openai")
    
    ingest_collection(collection_id, spec_source, LLMConfig(
        enabled=True,
        spec=llm_spec,
    ))
```

graph-tool-call 은 xgen 에 의존하지 않음. xgen 이 config 주는 쪽, graph-tool-call 이 받는 쪽.

---

## 4. Stage 1 — Retrieval + Target Selection

**입력:** `requirement: str`

**출력:**
```json
{
  "target": "seltProductDetailInfo",
  "confidence": 0.92,
  "entities": {
    "keyword": "quarzen 티셔츠",
    "locale": "ko"
  },
  "output_shape": "single",
  "reasoning": "..."
}
```

### 4.1 알고리즘

**(a) Retrieval prefilter (결정론):** graph-tool-call 의 기존 `retrieve_with_scores()` 그대로 사용.
```python
candidates = tg.retrieve_with_scores(requirement, top_k=20)
# BM25 + graph + (optional) annotation 채널
```
embedding prefilter 는 생략. 기존 BM25 + graph 가 top-20 recall 을 충분히 내는 것을 실측으로 확인 (x2bee `"product search"` → `seltSearchProduct` top-10 안에 들어옴).

향후 recall 부족 증거가 나오면 embedding 채널을 **그때** 연결. 지금은 YAGNI.

**(b) LLM structured pick:**
- 20개의 catalog 에 **ai_metadata 포함**:
  ```
  {
    function_name,
    description[:80],
    one_line_summary,       // Pass 2 에서 생성
    when_to_use,            // Pass 2
    pairs_well_with         // Pass 2 (이름만)
  }
  ```
- system prompt: "고른 target 1개와 추출한 entities 를 반환"
- OpenAI structured output (JSON schema 강제)

**context 크기:** 20 × 200자 ≈ 4KB (ai_metadata 포함 확장). ai_metadata 없을 땐 20 × 100자 ≈ 2KB.

### 4.2 오류 처리

- Retrieval 이 top-20 모두 low score 면 → "적합한 도구 없음" 에러. 사용자 재질의 유도.
- LLM 이 JSON schema 위반 시 → 1회 retry. 실패하면 fallback: top-1 embedding 결과로 진행 (entities 는 빈 dict).

### 4.3 Stage 1 의 성능 지표
- Target 정확도 (샘플 요구사항 N개에 대해 "맞는 target 선정" 비율)
- Entity 추출 재현율
- LLM 응답 latency p50/p95

---

## 5. Stage 2 — Path Synthesizer

**입력:** Stage 1 output (`target`, `entities`)
**출력:** Plan (Plan 스키마는 §9 참조) OR "ambiguous" 플래그 (Disambiguation 발동)

### 5.1 DAG 구성 알고리즘 (Bottom-up)

```python
def synthesize(target, entities, collection_defaults):
    plan = {"steps": [], "output_binding": None}
    context = entities | collection_defaults   # 이미 아는 값들
    
    needed = target.consumes.required_only()   # 필수 입력만 먼저
    resolved = {}                              # {field: source_step_id}
    pending = list(needed)
    visited = set()
    
    while pending:
        field = pending.pop(0)
        if field.semantic_tag in available_tags(context, resolved):
            resolved[field.name] = bind_from_available(field, context, resolved)
            continue
        
        # graph 에서 이 semantic 을 produces 하는 tool 찾기
        producers = graph.producers_of(field.semantic_tag)
        if not producers:
            raise UnsatisfiableFieldError(field)
        
        # 후보 여러 개면 "ambiguous" 로 분기 (Stage 3 LLM)
        if len(producers) > 1 and not strictly_better(producers):
            return AmbiguousPlan(target, candidates=producers)
        
        # prerequisite 추가 (재귀)
        producer = producers[0]
        if producer.name in visited:
            raise CyclicDependencyError
        visited.add(producer.name)
        
        step = build_step(producer)
        plan.steps.insert(0, step)  # 앞쪽에 삽입 (위상 순서)
        
        # producer 의 consumes 를 다시 확인
        pending.extend(producer.consumes.required_only())
    
    # target 을 마지막 step 으로 추가
    plan.steps.append(build_step(target, bindings=resolved))
    plan.output_binding = f"$.{target.step_id}.body"
    
    return plan
```

### 5.2 "strictly_better" 판단

여러 producer 후보 중:
- IO Contract confidence 높은 순
- 경로 짧은 순 (재귀 depth)
- similar_to weight 높은 순 (requirement 와 가까운)
- 모두 비슷하면 → Ambiguous 플래그

### 5.3 초기 버전 범위

- **선형 chain** (각 step 1회 호출): 지원
- **다중 참조** (한 step 이 이전 N개 step 의 출력 조합): 지원
- **Fan-out** (배열 전체 loop): **초기 범위 밖** — §10 확장 포인트
- **조건 분기** (if/else): **초기 범위 밖**

### 5.4 실패 경로

| 케이스 | 반환 |
|---|---|
| 필수 field 해소 불가 | `UnsatisfiableFieldError` — Stage 4 에 그대로 reveal |
| 순환 의존 | `CyclicDependencyError` — 보고 |
| 복수 경로 | `AmbiguousPlan` — Disambiguation 발동 |

---

## 6. Disambiguation (조건부)

**발동 조건:** Stage 2 가 `AmbiguousPlan` 반환.

**입력:** 후보 경로 2~N개 각각의 요약
```
후보 A: seltSearchProduct → seltProductDetailInfo
후보 B: getCategoryList → seltSearchProduct → seltProductDetailInfo
```

**LLM 호출:**
- system: "요구사항에 가장 맞는 경로 1개를 고르고 이유를 설명"
- user: requirement + 후보 경로 설명
- structured output: `{"chosen": "A", "reason": "..."}`

**context:** ~2KB

---

## 7. Stage 3 — Runner

**입력:** 확정 Plan

**동작:**
```python
async def run(plan: Plan):
    context = {}                              # step_id → result
    trace = ExecutionTrace(plan=plan)
    
    for step in topological_order(plan.steps):
        resolved_args = resolve_bindings(step.args, context)
        
        trace.emit("step.start", step_id=step.id, args=resolved_args)
        
        try:
            result = await tool_executor.execute(
                function_id=step.tool_function_id,
                args=resolved_args,
                timeout=step.timeout or 30,
            )
        except ToolExecutionError as e:
            trace.emit("step.error", step_id=step.id, error=str(e))
            return trace.fail(step.id, e)
        
        context[step.id] = result
        trace.emit("step.done", step_id=step.id, output_preview=preview(result))
    
    final = jsonpath_extract(context, plan.output_binding)
    trace.emit("plan.done", output=final)
    return trace.success(final)
```

### 7.1 Argument 바인딩 치환

바인딩 syntax: `${step_id.json_path}` — JsonPath 표준 사용 (jsonpath-ng 라이브러리).

```
args = {"goodsNo": "${s1.body.goods[0].goodsNo}",
        "langCd": "ko"}
context = {"s1": {"body": {"goods": [{"goodsNo": 12345, ...}]}}}
→ resolved = {"goodsNo": 12345, "langCd": "ko"}
```

### 7.2 에러 / 재시도 정책 (초기 버전)

| 에러 유형 | 동작 |
|---|---|
| HTTP 4xx | fail fast, trace 에 응답 body 포함 |
| HTTP 5xx | 최대 2회 재시도 (exponential backoff) |
| 타임아웃 | fail fast |
| JsonPath 미스 | fail fast — "step sX 의 bindings 가 실제 응답 구조와 불일치: [list of missing paths]" |
| Schema 검증 실패 | fail fast |

**재계획 (re-plan) 은 v1 범위 밖.** 실패 시 Stage 4 가 사용자에게 설명.

### 7.3 스트리밍

각 step 단위로 이벤트 emit. UI 는 step 단위 진행 상황 표시.

---

## 8. Stage 4 — Response Synthesis

**입력:** requirement + ExecutionTrace

**동작:**
```python
def synthesize_response(requirement, trace):
    if trace.success:
        # 최종 output 의 관련 필드만 추림 (schema-aware projection)
        relevant = project_relevant_fields(trace.output, requirement)
        prompt = f"""
        요구사항: {requirement}
        실행 결과 요약: {relevant}
        사용자에게 자연스럽게 답변.
        """
    else:
        prompt = f"""
        요구사항: {requirement}
        실행 중 실패: step={trace.failed_step}, 이유={trace.error}
        부분 결과: {trace.partial_results}
        사용자에게 무엇이 됐고 무엇이 안 됐는지 설명.
        """
    return llm.complete(prompt)
```

**context:** 요약된 결과 기준 ~1KB. 전체 response 를 그대로 넘기지 않음 — `project_relevant_fields` 가 requirement 에 관련된 필드만 추림.

---

## 9. 핵심 데이터 계약

### 9.1 Intent Schema (Stage 1 출력)

```typescript
type Intent = {
  target: string;                    // function_name
  confidence: number;                // 0.0 ~ 1.0
  entities: Record<string, any>;     // {keyword: "...", locale: "ko", ...}
  output_shape: "single" | "list" | "count";
  reasoning?: string;                // 디버그용
}
```

### 9.2 Plan Schema (Stage 2 출력)

```typescript
type Plan = {
  id: string;                         // uuid (캐시 키 포함)
  goal: string;                       // Intent 의 요약
  steps: PlanStep[];
  output_binding: string;             // JsonPath "$.s2.body" 등
  metadata: {
    created_at: string;
    target: string;
    disambiguation_used: boolean;
  };
}

type PlanStep = {
  id: string;                         // "s1", "s2", ...
  tool: string;                       // function_name
  tool_function_id: string;           // DB 룩업용 slug
  args: Record<string, string>;       // {"goodsNo": "${s1.body.goods[0].goodsNo}", ...}
  timeout_ms?: number;
  retryable?: boolean;
  rationale?: string;                 // "검색 결과로 goodsNo 획득"
}
```

### 9.3 ExecutionTrace Schema (Stage 3 출력)

```typescript
type ExecutionTrace = {
  plan_id: string;
  success: boolean;
  steps: StepTrace[];
  output?: any;                       // 성공 시
  failed_step?: string;               // 실패 시
  error?: ErrorDetail;                // 실패 시
  duration_ms: number;
  started_at: string;
  ended_at: string;
}

type StepTrace = {
  id: string;
  tool: string;
  args: Record<string, any>;          // resolved (바인딩 치환 후)
  output?: any;
  error?: ErrorDetail;
  duration_ms: number;
  retries: number;
}
```

---

## 10. 하드코딩 제거 매핑표

| 현 하드코딩 | 제거 방법 | 대체 메커니즘 |
|---|---|---|
| `_SYNONYM_CLUSTERS` (goods↔product) | 제거 | Pass 2 `primary_resource` + `semantic_tag` (LLM per-tool enrichment) |
| `selt`, `sel` verb 특수 케이스 | 제거 | Pass 2 `canonical_action` (LLM 이 context 읽고 분류) |
| `*Id/*No/*Seq` 접미사 heuristic | 제거 | Pass 1 field name + type exact match (동일 swagger 안에선 충분) + 필요시 Pass 2 semantic_tag |
| `search-bridge` 예외 | 제거 | Pass 2 `pairs_well_with` + `canonical_action = search` |
| `_is_single_resource_path` 필터 | 제거 | IO Contract 의 produces/consumes 가 판단 |
| `_VERB_TO_INTENT` CRUD 사전 | **유지** (Pass 1 fallback) | Pass 2 가 LLM 으로 action 태깅 담당. Pass 2 생략 시 이 사전이 fallback |

---

## 11. 확장 포인트

### 11.1 Fan-out (foreach)

**시나리오:** "카트의 모든 상품 상세 보여줘"

**Plan schema 확장:**
```typescript
type PlanStep = {
  // ... 기존 필드
  foreach?: {
    source: string;                 // "${s1.body.items[*]}"
    item_alias: string;             // "item"
  };
  // args 안에서 `${item.goodsNo}` 참조 가능
}
```

**Runner 확장:** foreach step 은 N회 호출 후 결과를 배열로 묶어 context 에 저장.

### 11.2 조건 분기 (if/else)

**Plan schema 확장:** step 에 `condition` 필드 (JsonPath 기반 부울 식). Runner 가 evaluate 후 skip/execute.

### 11.3 Workflow Template Library

- 성공한 Plan 을 `workflow_templates` 테이블에 승격
- 새 requirement → embedding 기반 template match → 재사용
- Stage 1~2 skip 가능 → 더 빠름
- Intent 유사 판정 임계값 튜닝 필요

### 11.4 Interactive Refinement

- Runner 가 특정 step 에서 `user_input_required` 이벤트 발행
- UI 가 사용자에게 선택지 제시
- 응답 받아 Runner 재개 (suspend/resume)
- 민감 액션 (결제, 삭제) 에 필수

### 11.5 Self-healing Re-plan

- Runner 실패 시 ExecutionTrace + 에러를 Stage 1~2 에 다시 넘겨 1회 re-plan
- 예: "빈 배열 반환 → 검색 키워드 재조정" 같은 케이스

---

## 12. 마이그레이션

### 12.1 기존 자산 활용

- `graph_tool_call.analyze.dependency.detect_dependencies`: **유지**. IO Contract 가 못 잡는 구조적 엣지는 여전히 여기서. 단 반응성 패치 (`selt`, `_SYNONYM_CLUSTERS`, `*No/*Seq`, `search-bridge`) 는 Pass 2 enrichment 정착 시 **단계적 제거**.
- `graph_tool_call.retrieval`: **유지**. Stage 1 의 prefilter 로 그대로 활용 (BM25 + graph).
- `graph_tool_call.ontology.llm_provider`: **유지**. Pass 2 enrichment 의 `enrich_tool_semantics` 메서드 추가.
- `tool_executor.execute_collection_tool`: **유지**. Stage 3 Runner 가 호출.
- `APICollectionLoader` Canvas 노드: **유지** (그래프 + ai_metadata 로드 역할).
- `Agent Xgen` 노드: **유지** (범용 ReAct / 일반 채팅 용도). API collection 시나리오에 쓰일 땐 `Agent Planflow` 로 대체 권장.

### 12.2 Canvas 노드 구성 변경

```
기존:  Input → APICollectionLoader → Agent Xgen → Output
신규:  Input → APICollectionLoader → Agent Planflow → Output
              (graph/ai_metadata/io_contracts 로드)  (Stage 1~4 통합)
```

`Agent Planflow` 내부 구조:
```
┌── Stage 1: retrieval + target pick  (LLM 1회)
├── Stage 2: path synthesizer           (결정론, DAG)
├── (conditional) disambiguation        (LLM 조건부)
├── Stage 3: runner (streaming)          (결정론, HTTP)
└── Stage 4: response synthesis          (LLM 1회, streaming)
```

설정 UI 는 `Agent Xgen` 과 공용 컴포넌트 재사용 (provider/model/api_key/temperature/max_tokens). 전용 파라미터 (`enable_disambiguation`, `max_plan_steps`) 만 추가.

### 12.3 점진 마이그레이션 전략

1. **Phase A:** L0 Knowledge Base 구축 — IO Contract 추출 (결정론) + `OntologyLLM.enrich_tool_semantics` 메서드 추가. 기존 graph 와 공존.
2. **Phase B:** Stage 3 Runner 독립 구현 (plan fixture 로 단위 테스트).
3. **Phase C:** Stage 2 Path Synthesizer — DAG + exact field match + semantic_tag 보강.
4. **Phase D:** Stage 1 + 4 LLM 호출 구현 (structured output). 기존 `retrieve_with_scores` 를 Stage 1 prefilter 로 연결.
5. **Phase E:** Canvas 노드 `Agent Planflow` 개발. 설정 UI 는 `Agent Xgen` 컴포넌트 재사용.
6. **Phase F:** 평가 세트로 A/B 측정. 안정화 후 기존 반응성 패치 (`selt`, synonym 등) 제거.

---

## 13. 운영 리스크 및 완화

| 리스크 | 영향 | 완화 |
|---|---|---|
| IO Contract semantic_tag 오태깅 | Stage 2 가 틀린 path 생성 | ingest 시 LLM 태깅 → 관리자 UI 검수/오버라이드 |
| Stage 1 target 오선정 | 전혀 다른 도구 실행 | confidence threshold → 낮으면 disambiguation 강제 |
| Stage 2 Ambiguous 빈발 | 매 요청 LLM 추가 호출 | IO Contract 개선으로 장기적으로 완화. 초기엔 허용 |
| Runner JsonPath miss | 실행 실패 | plan validate 단계에서 response schema 와 bindings 교차 검증 (Stage 2 출력 직후) |
| HTTP 외부 장애 | 사용자 체감 실패 | retry + 명확한 trace + Stage 4 에서 "일부 성공/실패" 구분 |
| Embedding API 비용 | ingest 비용↑ | ingest 시 1회만. 요청당 embed 는 requirement 1회만 |
| LLM structured output 깨짐 | Stage 1 파싱 실패 | 1회 retry → 실패 시 top-1 embedding 결과 fallback |

---

## 14. 측정 지표 (성공 기준)

### 14.1 성능

- Latency p50 / p95 (목표: p50 ≤ 3s, p95 ≤ 6s)
- LLM 호출 수 / 요청 (목표: ≤ 2.5 평균)
- Context 총량 / 요청 (목표: ≤ 3KB 평균)

### 14.2 품질

평가 세트: 요구사항 20~50개 (각 collection 당).

- **Stage 1 target 정확도:** 고른 target 이 사람 판단과 일치하는 비율
- **Stage 2 path 정확도:** 생성된 plan 이 유효한 실행 시퀀스인 비율
- **End-to-end 성공률:** 사용자 요구사항 → 의미 있는 답변까지 성공한 비율
- **Ambiguity rate:** Disambiguation 발동 빈도 (낮을수록 graph 품질 좋음)

### 14.3 비용

- OpenAI 토큰 소비 / 요청 (입력/출력 분리)
- Embedding 호출 수 (ingest + 요청별 1회)

### 14.4 감사성

- 모든 Plan artifact 조회 가능
- 실패 시 failed_step + error + partial_results 복원 가능

---

## 15. 비전과의 정합성

사용자가 그린 그림:

> Swagger → tool list 정의 → 사전 graph 관계 구축 →
> 워크플로우에서 컬렉션 노드 연결 + 요구사항 입력 →
> 필요한 API 들 찾아 req/res 세팅 후 순서대로 호출 → 결과 반환

이 아키텍처의 대응:

| 사용자 의도 | 이 설계에서 |
|---|---|
| "사전 graph 관계 구축" | L0 Knowledge Base (Pass 1 구조적 + Pass 2 LLM 의미 주석) |
| "요구사항 입력" | Stage 1 입력 |
| "필요한 API 찾기" | Stage 1 (retrieval + target pick) + Stage 2 (DAG 구성) |
| "req/res 세팅" | Stage 2 의 argument bindings (exact field match + semantic_tag) |
| "순서대로 호출" | Stage 3 Runner (DAG topological) |
| "결과 반환" | Stage 4 Response Synthesis |

**정합성 완전.** LLM 은 의미 해석이 필요한 지점에만 최소한으로 사용:
- **Ingest 시 Pass 2** — description 을 읽고 의미 주석 (1회, 영속 저장)
- **Runtime Stage 1** — 사용자 자연어 → target tool + entities
- **Runtime Stage 4** — 실행 결과 → 자연어 응답

Request/response schema 는 LLM 이 일절 건드리지 않음 (swagger 가 source of truth).

---

## 16. 결정 사항

### 해결된 항목 (2026-04-23)

| # | 주제 | 결정 | 근거 |
|---|---|---|---|
| 1 | Field semantic 매칭 방식 | **Pass 1 exact match (기본) + Pass 2 LLM semantic_tag (보강)**. embedding clustering 불필요 | 동일 swagger 안에선 field 이름 일관. cross-convention 은 LLM 이 해결 |
| 2 | LLM 모델 선택 | **xgen agent 노드 config 재사용**. Stage 1/4 는 사용자 노드 설정 상속. Pass 2 는 컬렉션별 별도 설정 (기본 gpt-4.1-mini) | UX 일관성, 기존 provider/key 관리 재사용 |
| 3 | Ingest embedding 모델 | **사용 안 함 (v1)**. 필요시 `text-embedding-3-small` 추후 연결 | BM25 + graph 가 Stage 1 top-20 recall 확보 (실측) |
| 4 | Plan / ExecutionTrace 영속성 | **로그 기반 (DB 테이블 없음)**. 구조화 JSON 이벤트로 plan 생명주기 기록 | YAGNI. 필요 기능 (history UI, template auto-promotion) 생길 때 해당 테이블 추가 |
| 5 | Canvas 노드 구성 | **신규 노드 `Agent Planflow`**. `Agent Xgen` 은 유지 (범용 ReAct), `Agent Planflow` 는 API collection 전용 Plan-and-Execute. 설정 UI 공용화 (provider/model/key) | 기존 자산 유지 + 특화 경로 분리. 코드 간결성 |
| 6 | Plan 실행 범위 (v1) | **선형 chain 만**. Fan-out / 조건 분기 / parallel / re-plan 은 v2+. Plan schema 는 optional 필드로 **확장 가능하게 설계** | v1 목표 (30s→5s + 정확도) 는 선형으로 달성. 복잡 케이스는 사용자에게 명시적 에러 |

### 미결 항목

모두 해결됨 (2026-04-23).

---

## 17. 참고 문서

- [pathfinder-plan.md](./pathfinder-plan.md) — 기존 로드맵 (이 문서 확정 후 섹션 3.7 업데이트 필요)
- [pathfinder-bug-analysis.md](./pathfinder-bug-analysis.md) — ingest 파이프라인 과거 이슈
- [xgen-ai-chat-architecture.md](./xgen-ai-chat-architecture.md) — AI chat / 사이드패널 / canvas 통합

---
