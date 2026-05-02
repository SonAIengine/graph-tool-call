# graph-tool-call Roadmap

> 작성일: 2026-04-09
> 상태: Phase 0~4.5 완료 (255+ tests). 다음 6~9개월 고도화 방향.
>
> 관련 문서:
> - [memo/differentiation-analysis.md](../memo/differentiation-analysis.md) — 학술 차별화 9개 분석
> - [docs/wbs/README.md](wbs/README.md) — Phase 0~4.5 WBS
> - [docs/benchmarks.md](benchmarks.md) — 현재 벤치마크 결과

---

## 요약

현재 graph-tool-call은 **"도구 검색 라이브러리"**로 완성도 높음. 다음 단계는 **"도구 검색 + 실행 + 거버넌스 레이어"**로 카테고리 확장.

고도화 후보 15개를 2축 — **거버넌스**(다른 작업의 전제 + 안정성/보안/관측성)와 **효과**(사용자 체감 + 학술 임팩트) — 로 평가해 우선순위를 매겼다. 1번과 2번 우선순위는 의존성이 명확하므로 순서 고정, 3번 이후는 시간/리소스 제약에 따라 3가지 시나리오로 분기.

---

## 1. 배경 — 현재 gap

### 1.1 README가 약속한 것 vs 실제 구현

README Quick Start는 `plan_workflow()`에 대해 이렇게 쓰여 있다:

> `plan_workflow()` returns ordered execution chains with prerequisites — **reducing agent round-trips from 3-4 to 1**.

하지만 현재 `graph_tool_call/workflow.py`에는 **계획 작성/편집 메서드만 있고 실행 메서드가 없다** (`execute` / `run` / `invoke` 키워드 0개). 단일 tool 실행은 `ToolGraph.execute()`(tool_graph.py:629)에 있지만, 이를 chain으로 묶는 orchestration 레이어가 부재. 즉 "round-trip 1회" 약속은 **절반만 지켜진 상태**.

### 1.2 학술 차별화 9개 중 1개만 구현

[memo/differentiation-analysis.md](../memo/differentiation-analysis.md)는 9개의 학술 차별화 후보를 정리해두었다:

| # | 후보 | Tier | 구현 상태 |
|---|---|:---:|:---:|
| 3.1 | MCP Annotation-Aware Retrieval | 1 | ✅ (Phase 2.5) |
| 3.2 | Execution Trace → Causal Tool Graph | 1 | ❌ |
| 3.3 | Token-Budget Constrained Graph Selection | 1 | ❌ |
| 3.4 | Dynamic Tool Graph | 2 | 부분 |
| 3.5 | Cross-Server Tool Dependency | 2 | ❌ |
| 3.6 | Tool Name Disambiguation | 2 | ❌ (prefix 회피만) |
| 3.7 | Cross-Primitive Retrieval | 3 | ❌ |
| 3.8 | Failure-Aware Closed-Loop Retrieval | 3 | ❌ |
| 3.9 | Stateful Session-Aware Retrieval | 3 | 부분 (history 파라미터만) |

### 1.3 코드 베이스 분석으로 발견한 추가 gap

학술 차별화 분석에 **없는** 실용 gap 7개:

| 코드 | 위치 | gap |
|---|---|---|
| `graph_tool_call/workflow.py` | `WorkflowPlan` | `execute_plan()` 부재 |
| `graph_tool_call/mcp_proxy.py:164-211` | backend tool 수집 | schema 검증/provenance/ACL 부재 |
| `graph_tool_call/retrieval/engine.py:111-188` | 5개 scorer | Score Provider 플러그인 인터페이스 부재 |
| `graph_tool_call/__init__.py` | public API | trace export / debug API 부재 |
| `graph_tool_call/retrieval/graph_search.py:38-100` | `_get_category_index()` | 매 query마다 재구축 |
| `graph_tool_call/ingest/` | 단일 spec | spec 경계를 넘는 federation 부재 |
| `graph_tool_call/ingest/` | 6종 format | 새 format 추가 시 adapter interface 부재 |

---

## 2. 후보 15개 간략 설명

후보는 **그룹 1 (사용자 즉시 체감)**, **그룹 2 (시스템 견고성)**, **그룹 3 (검색 품질 / 학술)** 으로 분류.

### 그룹 1 — 사용자 즉시 체감

#### A. Workflow Execution Engine
**현상**: `plan_workflow()`는 계획만 생성, 실행은 사용자/LLM 책임.
**작업**: `execute_plan(goal, initial_args)` 추가. `params_from` path expression parser로 step 간 데이터 자동 전달. 실패 시 skip / rollback / abort 정책. dry-run 모드.
**효과**: README 약속("round-trip 3-4회 → 1회") 완성. LLM agent가 `execute_plan` 1번 호출로 multi-step workflow 처리. 다른 학술 후보 5개(P4, P5, B enforcement, C trace, end-to-end 벤치마크)의 전제.
**Effort**: 1.5~2주 (HTTP 실행 인프라는 이미 존재, chain orchestration만 추가)

#### B. Tool Poisoning Defense
**현상**: MCP backend tool schema를 그대로 신뢰. 악성 서버가 description에 prompt injection 삽입 가능 (Invariant Labs 보고).
**작업**: Schema 해시 기반 mutation detection / tool provenance 추적 / annotation 기반 ACL (`readOnlyHint=true`만 unprivileged 노출) / prompt injection 패턴 탐지.
**효과**: 회사 도입 시 보안팀 차단 사유 제거. USENIX Security / IEEE S&P 같은 보안 학회 논문 타겟 가능 (Tool Poisoning을 retrieval layer에서 막는 first work).
**Effort**: 2~3주

#### C. Observability + Trace Export
**현상**: 기본 logging만. "왜 이 도구가 검색되지 않았지?" 디버그 불가.
**작업**: `RetrievalEngine`에 `TraceContext` 추가 — 단계별 점수 + 최종 순위 캡처. OpenTelemetry span export. CLI `--trace-out trace.json`.
**효과**: 사용자가 자기 데이터로 튜닝 가능. P4/P5의 데이터 소스 겸용. 도입 전 검증 가능성 ↑.
**Effort**: 1주

#### F. Cross-Spec Federation
**현상**: 여러 OpenAPI spec ingest 시 단순 union. spec A의 `getUser` 출력과 spec B의 `userId` 파라미터가 연결되지 않음.
**작업**: spec 경계를 넘는 parameter schema 매칭. provenance metadata.
**효과**: 회사 internal API 여러 개 통합 케이스 — 실제 도입 시나리오에서 가장 흔한 요구.
**Effort**: 2주 (P1과 인프라 공유)

### 그룹 2 — 시스템 견고성 (인프라)

#### D. Pluggable Score Provider SPI
**현상**: `retrieval/engine.py`에 5개 scorer가 hardcoded. 새 score 추가하려면 engine 직접 수정.
**작업**: `ScoreProvider` Protocol + `register_score_provider()` API. 기존 5개를 SPI에 맞춰 refactor.
**효과**: 학술 후보 P3/P4/P5의 score 통합이 모두 plug-in. 외부 기여자가 새 score (popularity, latency, user feedback 등)를 추가 가능.
**Effort**: 1주

#### E. Incremental Re-indexing
**현상**: tool 추가 시 BM25 index와 embedding을 처음부터 재구축. `_get_category_index()`는 매 query마다 재구축 (1068 tools × tokenization = O(n)).
**작업**: BM25/embedding add-remove API. category index lazy invalidation.
**효과**: 1068+ tools 환경에서 latency 급감. MCP server를 동적으로 추가/제거하는 환경(Cursor, Claude Code)에서 직접 이득.
**Effort**: 1주

#### G. Anti-Corruption Adapter Layer
**현상**: ingest format 6종(OpenAPI/MCP tools/MCP server/Python fn/manual/Arazzo). 새 format 추가 시 ingest 모듈에 산발적 코드.
**작업**: `IngestAdapter` 추상 interface. 기존 6종 refactor. gRPC + GraphQL adapter PoC.
**효과**: 외부 기여 진입 장벽 ↓. 신규 format 200~300 LOC로 추가 가능.
**Effort**: 2주

### 그룹 3 — 검색 품질 / 학술 차별화

#### P1. Cross-Server Tool Dependency
**현상**: 같은 spec 내 의존성만 감지. cross-server 흐름(Slack → Jira → GitHub)은 별개로 취급.
**작업**: `mcp_proxy.py` cross-backend ingest 시 parameter schema 매칭. 새 edge type 불필요 (`REQUIRES`로 충분), backend metadata만 추가.
**효과**: MCP-Bench retrieval 오류의 50%를 차지하는 cross-server 문제 직접 해결. 논문 1편 핵심 contribution.
**Effort**: 2~3주

#### P2. Tool Name Disambiguation
**현상**: MCP 생태계 59% 이름 충돌("search" 32개 서버). 현재는 `serverName__toolName` prefix로 회피.
**작업**: 동일 이름 도구를 (signature + ontology context)로 자동 구분. disambiguation key 생성.
**효과**: LLM이 prefix 신경 쓰지 않아도 됨. 논문 1편의 sub-contribution으로 포함 가능.
**Effort**: 2주

#### P3. Stateful Session-Aware Retrieval
**현상**: history 파라미터로 "이미 호출한 도구"를 demote만 함. 다음 도구 예측 없음.
**작업**: Markov chain on tool graph로 다음 도구 확률 계산. `RetrievalEngine`에 새 score source.
**효과**: multi-turn 대화 retrieval 정확도 ↑. 짧은 후속 질문("이제 그거 취소해") 처리력 강화.
**Effort**: 3~4주 (평가 인프라 포함)

#### P4. Failure-Aware Closed-Loop Retrieval
**현상**: 도구 실패해도 retrieval 순위에 영향 없음.
**작업**: 실행 trace → edge weight online learning. 최근 실패율 높은 도구 자동 강등. `SIMILAR_TO` fallback 제안.
**효과**: self-healing. 운영 중 안 쓰이는 도구 자동 정리.
**전제**: **A 필요** (실행 trace가 있어야 학습 가능)
**Effort**: 3주

#### P5. Execution Trace → Causal Tool Graph
**현상**: 의존성 그래프가 정적 metadata(OpenAPI/CRUD)에만 의존.
**작업**: 실행 trace에서 interventional causal discovery로 인과적 의존성 자동 발견.
**효과**: Tier 1 단독 contribution (causal discovery + tool learning 교차점, 미개척). 사용할수록 똑똑해지는 시스템.
**전제**: **A 필요**
**Effort**: 6~8주 (이론 + 평가)

#### P6. Token-Budget Constrained Graph Selection
**현상**: top-k=5 고정. 도구 토큰 비용 예측 불가.
**작업**: dependency-constrained knapsack ILP formulation. DAG 활용 근사 알고리즘. approximation ratio 증명.
**효과**: Cursor 40 한도, OpenAI 권장 20개 제약 해결. 비용 예측 가능. ICML/NeurIPS 타겟.
**Effort**: 8주 (이론 작업 중심)

#### P7. Cross-Primitive Retrieval
**현상**: MCP의 3대 primitive 중 Tools만 검색.
**작업**: Resources/Prompts 노드 추가. 새 edge type(`PROVIDES_CONTEXT`, `TEMPLATES`). heterogeneous graph 검색.
**효과**: MCP 잠재력 100% 활용.
**블로커**: Resources/Prompts 사용하는 실제 MCP 서버가 적어 평가 데이터셋 부족
**Effort**: 6주 (+ 평가 데이터 수집)

---

## 3. 우선순위 매트릭스

거버넌스 = 다른 작업의 전제 + 안정성/보안/관측성
효과 = 사용자 체감 + 잠금 해제 + 학술/시장 임팩트

| 순위 | 후보 | 거버넌스 | 효과 | 합계 | 전제 |
|:---:|---|:---:|:---:|:---:|---|
| 1 | **A. Workflow Execution** | ★★★★★ | ★★★★★ | 10 | 없음 |
| 2 | **B. Tool Poisoning Defense** | ★★★★★ | ★★★★ | 9 | 없음 |
| 3 | **D. Score Provider SPI** | ★★★★★ | ★★★ | 8 | 없음 |
| 4 | **C. Observability + Trace** | ★★★★ | ★★★ | 7 | 없음 |
| 5 | **P6. Token-Budget Knapsack** | ★★★ | ★★★★ | 7 | 없음 |
| 6 | **P1. Cross-Server Dependency** | ★★ | ★★★★ | 6 | 없음 |
| 7 | **F. Cross-Spec Federation** | ★★ | ★★★★ | 6 | P1 인프라 공유 |
| 8 | **G. Adapter Layer** | ★★★★ | ★★ | 6 | 없음 |
| 9 | **E. Incremental Re-indexing** | ★★★ | ★★★ | 6 | 없음 |
| 10 | P5. Causal Tool Graph | ★★★ | ★★★★★ | 8* | **A 필요** |
| 11 | P4. Failure-Aware | ★★★ | ★★★ | 6* | **A 필요** |
| 12 | P2. Name Disambiguation | ★★ | ★★★ | 5 | 없음 |
| 13 | P7. Cross-Primitive | ★★ | ★★★ | 5 | 없음 |
| 14 | P3. Stateful Session | ★ | ★★★ | 4 | 없음 |

`*` 전제 작업(A) 미완료 시 진입 불가

---

## 4. 마일스톤

### 권장 진행 (6~8개월, 시나리오 C)

```
┌─────────────────────────────────────────────────────────┐
│ Week 1         D. Score Provider SPI            [1w]   │
│ Week 2-4       A. Workflow Execution            [3w]   │
│ Week 5-6       C. Observability + Trace         [2w]   │
│ Week 7-9       B. Tool Poisoning Defense        [3w]   │
├─────────────────────────────────────────────────────────┤
│ 마일스톤 1 (~9주) — v0.5 Release                         │
│   ✓ Workflow 완성 (README 약속 성립)                    │
│   ✓ Security defense                                    │
│   ✓ Observability + debug                               │
│   ✓ Score provider plugin SPI                           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Week 10-12     P1. Cross-Server Dependency      [3w]   │
│ Week 13-14     F. Cross-Spec Federation         [2w]   │
│ Week 15-16     P2. Name Disambiguation          [2w]   │
├─────────────────────────────────────────────────────────┤
│ 마일스톤 2 (~16주) — 논문 1 초안                          │
│   "MCP-Native Graph Tool Retrieval:                     │
│    Cross-Server Dependency + Name Disambiguation +      │
│    Annotation-Aware Defense"                            │
│   타겟: EMNLP Workshop / ACL Findings                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Week 17-24     P5. Causal Tool Graph            [8w]   │
│ Week 25-32     P6. Token-Budget Knapsack        [8w]   │
├─────────────────────────────────────────────────────────┤
│ 마일스톤 3 (~32주) — 논문 2                              │
│   "Token-Constrained Tool Selection as                  │
│    Graph Optimization"                                  │
│   타겟: ICML / NeurIPS                                  │
└─────────────────────────────────────────────────────────┘
```

### 대안 시나리오

#### 시나리오 A — 학술 우선 (4개월, 논문 1편)

시간이 제한적이고 논문 1편을 빨리 받고 싶은 경우.

```
Week 1          D. Score Provider SPI            [1w]
Week 2-4        P1. Cross-Server Dependency      [3w]
Week 5-6        P2. Name Disambiguation          [2w]
Week 7-9        B. Tool Poisoning Defense        [3w]
Week 10-16      논문 1 작성 (LiveMCPBench + ToolBench 평가)
```

**리스크**: A가 뒤로 밀려서 P4/P5가 영구적으로 막힘. 논문 2 불가능.

#### 시나리오 B — 프로덕션 우선 (2개월, 사용자 확보)

학술 의도 없이 실사용자 확보가 목표인 경우.

```
Week 1-3        A. Workflow Execution            [3w]
Week 4          C. Observability + Trace         [1w]
Week 5          E. Incremental Re-indexing       [1w]
Week 6-7        F. Cross-Spec Federation         [2w]
Week 8          블로그 + LangChain community 등록 (Phase 4 잔여)
```

**산출물**: PyPI 다운로드 ↑, real-world adopter case 1~2개, blog 기반 유입.

---

## 5. Phase 4 잔여 작업

시나리오와 무관하게 마무리할 가치 있음. 마일스톤 사이사이에 끼워 진행.

- [ ] 4-1d. 관계 검증 UI (confirm/reject)
- [ ] 4-2. LangChain community package 등록
- [ ] 4-3. 블로그: "Why Graph > Vector for Tool Retrieval"
- [ ] 4-4. (선택) LAPIS 포맷 출력
- [ ] 4-5. (선택) Rust (PyO3+petgraph) 최적화

---

## 6. 의사결정 포인트

다음 작업에 들어가기 전 확정해야 할 것:

1. **시나리오 선택** (A/B/C)
   - 논문 마감 있음 → A
   - 학술 의도 없음 → B
   - 시간 여유 있음 → C (권장)

2. **첫 작업 확정**
   - 시나리오 C → D (1주) 후 A (3주)
   - 시나리오 A → D (1주) 후 P1 (3주)
   - 시나리오 B → A (3주)

3. **Phase 4 잔여 끼워넣기 여부**
   - 4-2, 4-3은 시나리오 B 마지막에 통합
   - 4-1d는 Workflow Editor와 함께 A 작업 시 처리 가능

---

## 참고

- [memo/differentiation-analysis.md](../memo/differentiation-analysis.md) — 학술 차별화 9개 후보 상세
- [docs/wbs/README.md](wbs/README.md) — Phase 0~4.5 완료 내역
- [docs/benchmarks.md](benchmarks.md) — 현재 벤치마크 (Petstore 19 / GitHub 50 / MCP 38 / k8s 248 / GitHub full 1068)
- [docs/design/benchmark.md](design/benchmark.md) — 벤치마크 설계 근거
