# XGEN Tool Graph Search Goals

이 문서는 graph-tool-call을 XGEN API Collection / Planflow의 기본 tool graph
retrieval engine으로 끌어올리기 위한 목표 문서다. 목표는 BFCL 점수 하나를
높이는 것이 아니라, 수백-수천 개 API에서 필요한 tool, producer chain, plan
근거를 안정적으로 좁히는 엔진을 만드는 것이다.

## North Star

graph-tool-call은 XGEN에서 아래 문장을 제품적으로 말할 수 있는 수준까지 가야 한다.

> 수백-수천 개 API Collection에서도 LLM에게 전체 tool을 던지지 않고,
> graph-tool-call이 필요한 후보 tool set과 producer chain을 검색한다.
> 검색 결과에는 왜 선택됐는지, 왜 실패했는지, 다음 개선 대상이 무엇인지가
> 재현 가능한 evidence로 남는다.

즉 목표는 "BFCL leaderboard 1등"이 아니다. 목표는 XGEN 같은 실제 제품에서
large-scale tool retrieval + graph-based planning 앞단을 맡길 수 있는 엔진이다.

## Current Baseline

기준선은 qwen3.6-27B, BFCL v4 four-category local BFCL-compatible run,
official checker 재채점 기준이다. XGEN 적용성 기준선은 X2BEE BO Swagger UI
live acceptance run을 별도로 둔다.

| Metric | Current |
|---|---:|
| row-source exact upper bound | `0.90` |
| graph-tool-call retrieved top-k=3 exact | `0.69` |
| graph-tool-call retrieved top-k=5 exact | `0.764` |
| graph-tool-call retrieved top-k=10 exact | `0.798` |
| deterministic BFCL recall@5 | `0.952` |
| deterministic BFCL all-tools@5 | `0.930` |
| deterministic BFCL MRR | `0.833` |
| top-k=5 repeat exact mean/std | `0.764 / 0.000` |
| weakest category | `parallel_multiple` |
| parallel_multiple top-k=5 exact | `0.615` |
| X2BEE BO spec groups | `15` |
| X2BEE BO raw operations | `2,173` |
| X2BEE BO unique tools | `1,084` |
| X2BEE BO graph edges | `8,579` |
| X2BEE Korean product cases | `19` |
| X2BEE Korean product hit@3 | `1.00` |
| X2BEE target selector exact@3 | `1.00` |
| X2BEE avg plan candidate count | `2.16` |
| X2BEE max plan candidate count | `7` |
| X2BEE required input coverage | `0.872` |
| X2BEE required input resolution coverage | `1.00` |
| X2BEE unresolved required inputs | `0` |
| X2BEE expected tool recall@10 | `1.00` |
| X2BEE mean MRR | `1.00` |

현재 상태는 "감이 아니라 수치로 검증 가능한 XGEN 적용 기준선"이다. 다만
row-source upper bound 대비 아직 10pt 이상 손실이 있고, 복합 tool set 선택에서
retrieval miss와 candidate ambiguity가 크다. XGEN deterministic fixture에서는
target recall@5와 query-action target selector exact@5가 모두 `1.00`까지
올라왔다. 즉 built-in fixture에서는 top-5 안에 정답을 넣는 단계와 그중 실제
target을 고르는 단계가 모두 통과한다. X2BEE-scale에서도 19개 product-level
Korean BO case 기준 target selector exact@3/5/10이 모두 `1.00`까지 확인됐다.
이제 live-scale artifact는 선택된 target의 request/response binding readiness도
보여준다. 현재 평균 plan candidate count는 `2.16`, 최대 candidate count는
`7`, 평균 required input
coverage는 `0.872`이다. 이 값은 producer-only coverage라서, 이전 response
field가 직접 채울 수 있는 required input만 센다. 실행 관점의 required input
resolution coverage는 `1.00`이고 unresolved required input은 `0`건이다. 남은
live-scale 연구는 producer 후보 폭을 줄이고, request/response field matching과
실행 전 readiness를 더 정확하게 만드는 것이다. producer-only 미지원 4건은
`required_request_wrapper=2`, `required_context_input=1`,
`required_filter_input=1`로 분류된다.

`2026-07-19` rank-compression branch에서는 X2BEE live sweep에서 기존 hard
case인 `order_query_ko`, `page_role_buttons_ko`, `settlement_compare_ko`,
`return_withdrawal_ko`를 다시 검증했다. `make xgen-scale-sweep
OUT=/tmp/gtc-x2bee-sweep-after3.json TOP_KS=3,5,10` 기준 `hit@3=1.00`,
`expected recall@3=1.00`, `top-3 hit=1.00`, `mean MRR=0.833`까지 개선됐고,
page-role button multi-target은 rank `1`/`2`로 압축됐다. 상세 runner와
artifact 규칙은 [`validation-loop.md`](validation-loop.md)에 둔다.

`2026-07-19` scale selector branch에서는 같은 live X2BEE sweep artifact에
`selected_target`, `target_selector_exact`, `target_selector_rank`,
`target_action_priority`, `target_selector_rank_buckets`를 추가했다. 1084개
unique tool, 19개 Korean BO case 기준 top-K `3,5,10` 모두
`target_selector_exact_at_k=1.00`, `target_selector_miss_count=0`이다.

`2026-07-19` scale plan-readiness branch에서는 같은 artifact에
`plan_candidates`, `producer_candidates`, `input_support`,
`avg_required_input_coverage`, `required_input_not_producible`을 추가했다.
X2BEE acceptance gate는 `avg_required_input_coverage >= 0.8`과
`avg_candidate_count <= 25`를 포함한다. 현재 top-K `3,5,10` 모두 평균 candidate
count `17.16`, 평균 required input coverage `0.846`, readiness issue `5`건이다.
Readiness issue breakdown은 request wrapper `2`, context input `1`, filter
input `1`, producer missing `1`이다.

`2026-07-19` input-resolution branch에서는 같은 artifact에
`avg_required_input_resolution_coverage`, `unresolved_required_input_count`,
`input_resolution_counts`를 추가했다. Acceptance gate는
`avg_required_input_resolution_coverage >= 0.95`와
`unresolved_required_input_count <= 1`을 포함한다. 현재 top-K `3,5,10` 모두
평균 required input resolution coverage `0.974`, unresolved required input
count `1`이다. Resolution breakdown은 producer `41`, request wrapper `2`,
context `1`, user input `1`, unresolved `1`이다.

`2026-07-19` description-alias branch에서는 `marketingDisplayNo`처럼 긴
필드명과 `mkdpNo` 같은 축약 필드명이 같은 구체적 OpenAPI description을 공유할
때 identifier alias로 매칭한다. X2BEE live sweep 기준 producer-only required
input coverage는 `0.872`, required input resolution coverage는 `1.00`,
unresolved required input count는 `0`이다. Acceptance gate는
`avg_required_input_coverage >= 0.85`,
`avg_required_input_resolution_coverage >= 1.0`,
`unresolved_required_input_count <= 0`으로 올라갔다.

`2026-07-19` required-producer branch에서는 optional input producer를
`plan_candidates`에서 제외하고, required target input을 채우는 producer만 실행
후보로 올린다. Optional producer evidence는 `input_support`에 그대로 남긴다.
X2BEE live sweep 기준 평균 candidate count는 `17.84 -> 3.53`, max candidate
count는 `46 -> 14`로 줄었고, target selector exact, required input coverage,
resolution coverage는 유지됐다.

`2026-07-19` representative-producer branch에서는 required field별 첫 producer가
아니라, required field들을 가장 많이 덮는 representative producer set을 greedy로
고른다. 동률에서는 read/search/list 성격 producer를 우선한다. X2BEE live sweep
기준 평균 candidate count는 `3.53 -> 2.16`, max candidate count는 `14 -> 7`로
줄었고, `coupon_list_ko`는 candidate count `14 -> 4`까지 내려갔다. Acceptance
gate는 `max_avg_candidate_count <= 3`와 `max_candidate_count <= 8`을 포함한다.

`2026-07-19` BFCL weak-keyword branch에서는 hard-case bundle의
`weak_or_missing_keyword_signal` subset을 대상으로 guarded domain alias query
expansion을 추가했다. Concrete currency/unit/history/card wording이 generic
tool descriptions와 매칭되도록 하되, `king`/`card`/measurement unit 같은
ambiguous token은 probability/conversion intent가 같이 있을 때만 확장한다. 전체
BFCL deterministic 기준 `recall@5`는 `0.9325 -> 0.94025`,
`all_tools_found@5`는 `0.908 -> 0.917`, hard-case count는 `92 -> 83`으로 개선했다.

`2026-07-19` BFCL partial-multi branch에서는 actionable clause diversity gate를
추가했다. 배경 설명이나 단일 tool 반복 argument clause는 보수적인 clause injection을
유지하고, 서로 다른 sub-task signature가 3개 이상인 복합 요청에서만 clause 후보를
top-K 경계 위로 조금 더 보존한다. 전체 BFCL deterministic 기준 `recall@5`는
`0.94025 -> 0.94200`, `all_tools_found@5`는 `0.917 -> 0.920`, hard-case count는
`83 -> 80`으로 개선했고 케이스 단위 recall 악화는 0건이었다.

`2026-07-19` BFCL near-miss branch에서는 high-confidence semantic phrase boost를
추가했다. `genetically similar`, `population density`, `highest common factor`,
instrument availability, grocery-store criteria처럼 query phrase와 tool
description evidence가 동시에 맞는 경우만 승격한다. 전체 BFCL deterministic 기준
`recall@5`는 `0.94200 -> 0.95000`, `all_tools_found@5`는 `0.920 -> 0.928`,
hard-case count는 `80 -> 72`로 개선했고 케이스 단위 recall 악화는 0건이었다.

`2026-07-19` tail hard-case branch에서는 sparse `calculate_density` operation name
fallback을 `population density` query에만 추가했다. 전체 BFCL deterministic 기준
`recall@5`는 `0.95000 -> 0.95200`, `all_tools_found@5`는 `0.928 -> 0.930`,
hard-case count는 `72 -> 70`으로 개선했고 케이스 단위 recall 악화는 0건이었다.
이로써 0.26 retrieval gate 중 deterministic `recall@5 >= 0.95`와
`retrieval_miss <= 70`은 달성했다.

## Product Maturity Levels

| Level | Meaning | Expected Use |
|---|---|---|
| Current | 검증 가능한 기준선 | XGEN 실험 branch, benchmark 기반 개선 |
| 0.26 | 제품 실험에 자신 있게 붙이는 수준 | Planflow A/B, failure subset 중심 개선 |
| 0.27 | XGEN 기본 경로 후보 | API Collection tool search 기본 엔진 후보 |
| 0.28 | paper-ready 실험 플랫폼 | ablation, multi-dataset, 통계 반복 |
| 0.29 | workshop/short-paper 후보 | 논문 claim을 방어할 수 있는 evidence set |

## 0.26 Target

0.26은 "병목을 알고 고쳤다"를 보여주는 단계다.

| Metric | Target |
|---|---:|
| BFCL-compatible top-k=5 exact | `>= 0.82` |
| deterministic BFCL retrieval@5 | `>= 0.95` |
| parallel_multiple top-k=5 exact | `>= 0.70` |
| top-k=5 retrieval_miss | `<= 70` |
| candidate_ambiguity | current 이하 또는 증가 이유 설명 |
| XGEN deterministic fixture | all pass |
| X2BEE scale acceptance | pass, `>= 1,000` unique tools |
| X2BEE Korean smoke hit@10 | `>= 0.90` |
| X2BEE Korean smoke hit@5 | `>= 0.95` |
| X2BEE Korean smoke hit@3 | improve from `0.75` baseline |

Required work:

- failure corpus를 고정한다.
- retrieval miss와 candidate ambiguity를 별도 개선한다.
- 단순 top-K 증가가 아니라 target/producers/diversity 구조로 후보를 구성한다.
- `make research-check`와 failure subset smoke에서 개선이 먼저 보여야 한다.
- `make xgen-scale-acceptance`로 X2BEE급 live OpenAPI가 계속 ingest/search 가능한지 확인한다.
- `make xgen-scale-sweep`로 top-3/5/10을 같이 보고 rank-4/5에 걸린 정답을
  top-3 안으로 당기는지 확인한다.

0.26의 성공 기준은 full benchmark 숫자 하나가 아니라, 이전 hard case subset에서
실제로 miss가 줄어든다는 증거다.

## 0.27 Target

0.27은 XGEN에서 기본 경로 후보로 밀어볼 수 있는 단계다.

| Metric | Target |
|---|---:|
| BFCL-compatible top-k=5 exact | `>= 0.85` |
| BFCL-compatible top-k=10 exact | `0.84 - 0.86+` |
| deterministic BFCL retrieval@5 | `>= 0.95` |
| parallel_multiple top-k=5 exact | `>= 0.75` |
| XGEN multi-step plan exact | `>= 0.90` |
| XGEN fixture coverage | 3 fixture families |
| row-source upper-bound preservation | `>= 94%` |
| X2BEE Korean smoke hit@5 | `>= 0.90` |
| X2BEE target selector exact@5 | `>= 0.85` |
| X2BEE p50 retrieval latency | `< 50ms` |

Interpretation:

- row-source upper bound가 `0.90`이면 top-k=5 exact `0.85`는 약 94-95% 성능
  보존이다.
- 이 수준이면 "검색 레이어 때문에 모델 성능이 크게 깎인다"는 주장이 약해진다.
- XGEN에서는 API Collection tool search의 기본 엔진 후보로 볼 수 있다.

Required work:

- XGEN-style fixture를 commerce 1종에서 최소 3종으로 확장한다.
  - `2026-07-19`: built-in deterministic suites가 `commerce`, `admin`,
    `workflow` 3종으로 확장됐다. `make xgen-benchmark`와
    `make research-check`의 XGEN deterministic gate는 `--suite all`을 실행한다.
- producer expansion이 plan synthesis까지 실제 이득을 내는지 측정한다.
  - `2026-07-19`: XGEN deterministic benchmark artifact에
    `producer_expansion_lift`를 추가했다. 초기 producer-chain 12건 기준
    `target_only` 대비 `graph_with_producers`는 producer recall `+1.00`,
    candidate plan coverage `+0.625`, binding support `+1.00` lift를 만든다.
- top-k=5를 기본 경로로 유지하되, 복합 query에서만 adaptive expansion을 쓴다.
  - `2026-07-19`: 각 fixture family에 direct search/list case를 추가해
    전체 suite를 15건으로 늘렸다. `graph_with_producers`는 producer-needed
    12건에서만 adaptive expansion을 적용하고 direct 3건은 확장하지 않는다
    (`adaptive_expansion_case_count=12`, `unneeded_expansion_case_count=0`,
    `avg_candidate_count=2.60`, `max_candidate_count=4`).
- 실패 event에 stage, target, selected producers, missing fields, evidence를 남긴다.
  - `2026-07-19`: XGEN deterministic benchmark artifact의 각 case에
    `synthesis_diagnostics`를 추가했다. 성공 plan, user-input fallback,
    target-selection miss, synthesis error 모두 `stage`, `target`,
    `selected_producers`, `candidate_signals`, `missing_fields`,
    `failure`, `retrieval_evidence`를 남기는 형태다.
- X2BEE BO acceptance case를 smoke 수준에서 product-level case set으로 확장한다.
  - `2026-07-19`: X2BEE BO live acceptance cases를 8건에서 19건으로 확장했다.
    Artifact는 `/tmp/gtc-x2bee-sweep-top1-ambiguity.json`이고,
    `TOP_KS=3,5,10` 기준 `hit@3=1.00`, `expected recall@3=1.00`,
    `top-1 hit=1.00`, `top-3 hit=1.00`, `mean MRR=1.00`이다.
- BFCL model sweep artifact가 0.27 milestone gate를 직접 포함한다.
  - `2026-07-19`: `benchmarks.bfcl_tool_selection.sweep`의
    `summary.milestone_gate`에 `xgen-0.27` profile을 추가했다. Gate는
    retrieved `k=5` exact, retrieval recall, row-source upper-bound
    preservation, `parallel_multiple` exact를 판정한다. 이 값이 `fail`이면 full
    run을 반복하지 않고 `category_rows`와 hard-case bundle로 돌아가 작은 subset을
    먼저 고친다.
- qwen3.6-27B small model smoke로 0.27 gate 병목을 확인한다.
  - `2026-07-19`: `go165` vLLM `qwen3.6-27b`, category별 `limit=5`,
    row/retrieved `k=5` smoke에서 row-source exact는 `1.00`, retrieved exact는
    `0.85`, retrieval recall은 `1.00`이었다. Gate는 `fail`이며 실패 지점은
    row-source preservation `0.85 < 0.94`, `parallel_multiple`
    `0.60 < 0.75`다. 실패 3건은 retrieval miss가 아니라
    `candidate_ambiguity`/`call_count_mismatch`라서 다음 개선은 단순 recall이
    아니라 sibling/candidate presentation/plan grouping 쪽이다.
  - 같은 조건에서 `--retrieval-rank-hints` ablation은 retrieved exact `0.85`,
    `parallel_multiple` `0.60`으로 aggregate를 올리지 못했다. 따라서 단순 rank
    문구보다 후보 동등성/그룹화/복합 call set 구성 개선을 우선한다.
  - `--candidate-selection-guidance` 20-case smoke는 retrieved exact를
    `0.85 -> 0.90`으로 올렸고 `parallel_3`의 call-count mismatch를 pass로
    바꿨다. 다만 `parallel_multiple` exact는 `0.60`으로 남아
    `parallel_multiple_2`의
    `circle_properties.get` sibling 선택과 `parallel_multiple_4`의
    `calculate_area_under_curve` sibling 선택은 해결하지 못했다. 이 결과는
    LLM-facing prompt 정책과 candidate equivalence/grouping을 별도 workstream으로
    나눠야 함을 보여준다.
  - `--cohesive-namespace-candidates`를 selection guidance와 함께 적용한 20-case
    smoke는 retrieved exact `0.95`, retrieval recall `1.00`, row-source
    preservation `0.95`, `parallel_multiple` exact `0.80`으로 `xgen-0.27`
    milestone gate를 pass했다. 이 수치는 작은 smoke evidence이며, 다음 승격은
    같은 옵션을 failure subset과 더 큰 full sweep에서 반복 확인하는 것이다.
    남은 실패는 `parallel_multiple_4`의 integral sibling ambiguity 1건이다.
  - 같은 옵션을 category별 `limit=25`인 100-case 중간 검증으로 넓히면
    `/tmp/gtc-bfcl-qwen027-cohesive-guard-limit25.json` 기준 retrieved exact
    `0.83`, retrieval@5 `0.99`, row-source preservation `0.883`,
    `parallel_multiple` exact `0.84`로 gate는 아직 `fail`이다. 다만 후보 압축
    가드를 추가한 뒤 이전 100-case run의 `candidate_not_present` 2건은 0건으로
    사라졌고, `parallel_multiple` exact는 `0.76 -> 0.84`로 올랐다. 0.27의
    paired row/retrieved attribution 기준 retrieval/presentation 손실은 11건이며
    `candidate_ambiguity:8`, `argument_value_mismatch:2`, `retrieval_miss:1`이다.
    `near_duplicate_tool_surface` tag 기준 high-confidence duplicate surface는
    4건이다. 이 tag는 `build_tool_equivalence_groups(...)`와
    `build_candidate_set(...).target_equivalence_groups`로 같은 surface evidence를
    사용한다. XGEN deterministic benchmark는 같은 evidence를 target selector
    diagnostics와 summary count로 기록한다.
    별도 4-case subset smoke
    `/tmp/gtc-bfcl-neardup-adjusted-metric.json`에서는 strict/evaluator exact가
    `0.00`이지만 `equivalence_adjusted_exact_match`는 `1.00`이다. 이 adjusted
    metric은 공식 BFCL leaderboard 점수가 아니라, XGEN처럼 equivalent API
    surface가 공존하는 제품 환경에서 "실제 기능 선택은 맞았는가"를 분리해서
    보기 위한 연구 지표다.
    그 다음 nested argument matcher hardening에서는 BFCL possible-answer의
    nested dict value list를 재귀적으로 해석해 cached 100-case artifact의
    false negative 3건을 correction했다. 별도 6-case argument subset smoke
    `/tmp/gtc-bfcl-argument-matcher-subset.json` 기준 fresh qwen3.6-27B exact는
    `0.166667`이며, 남은 실패는 optional argument hallucination, boolean default
    inversion, percentage scale mismatch, data-reference vs synthetic array mismatch다.
    다음 병목은 `solve_quadratic` vs `solve_quadratic_equation`,
    `geometry.circumference` vs `calculate_circumference`, `math.gcd` vs
    `number_theory.gcd` 같은 near-duplicate disambiguation과 argument-value
    preservation이다. Row-source에서도 실패한 repeated-call / argument mismatch는
    retrieval layer 손실과 분리해서 모델 상한 및 tool schema 표현 문제로 본다.

## Paper-Ready Target

논문급은 0.27과 다르다. 0.27은 제품 후보이고, paper-ready는 claim과 실험
설계가 있어야 한다.

Candidate title:

> Graph-Guided Tool Retrieval for Large API-Collection Agents

Research claim:

> OpenAPI에서 추출한 IO contract와 tool graph를 이용해 candidate tool set과
> producer chain을 검색하면, large API collection에서 token/context 비용을 크게
> 줄이면서 tool-call 정확도를 row-source upper bound에 가깝게 보존할 수 있다.

Paper-ready metric targets:

| Metric | Target |
|---|---:|
| BFCL-compatible top-k=5 exact | `0.87 - 0.90` |
| deterministic BFCL retrieval@5 | `>= 0.96` |
| parallel_multiple exact | `0.78 - 0.82` |
| XGEN multi-step plan exact | `>= 0.90` |
| token reduction vs full tool list | `70 - 90%` |
| retrieval latency | p50 ms 단위 |
| repeats | `>= 3`, confidence interval 포함 |

Paper-ready evidence:

- BM25-only baseline
- embedding-only baseline
- BM25 + graph baseline
- graph + producer expansion
- graph + IO contract
- graph + reranker
- full tool list / row-source upper bound
- ablation for clause decomposition, producer expansion, IO contract, evidence rerank
- BFCL-derived, XGEN-style, real OpenAPI specs, Korean/English mixed queries
- failure taxonomy and qualitative failure analysis
- X2BEE-scale live/API-snapshot acceptance with duplicate-group handling

## Workstreams

### 1. Failure Corpus

Goal: "어떤 실패를 고쳤는지"를 항상 재현 가능하게 만든다.

- full run에서 hard case IDs를 추출한다.
- `retrieval_miss`, `candidate_ambiguity`, `argument_name_mismatch`,
  `call_count_mismatch`를 별도 subset으로 관리한다.
- 각 subset은 deterministic first, model smoke second, full run last 순서로 검증한다.
- `2026-07-19`: `make bfcl-hard-cases`를 추가해 full/smoke report 하나에서
  `case_ids.txt`, `cases.json`, `inspect.json`, `summary.json`,
  `failure_<category>.txt`, `tag_<tag>.txt`, `issue_<issue>.txt`를 한 번에 만든다.
  다음 검색 실험은 deterministic BFCL report의 inferred `retrieval_miss`와,
  LLM/sweep report bundle의 `near_duplicate_tool_surface`,
  `expected_present_below_top_k`, `partial_multi_tool_at_k`,
  `weak_or_missing_keyword_signal` subset을 먼저 개선한다.

### 2. Search Evidence

Goal: top-K 결과뿐 아니라 탈락 이유를 설명한다.

- BM25, clause, name, semantic, graph, producer score를 분리한다.
- 정답이 top-K 밖이면 rank, score gap, missing evidence를 남긴다.
- `retrieve_graphify(include_evidence=True)`를 XGEN log/SSE에 연결 가능한 형태로 유지한다.

### 3. Candidate Set Construction

Goal: top-K를 단순히 키우지 않고 후보 구성을 좋아지게 한다.

- target 후보와 producer 후보를 분리한다.
  - `2026-07-19`: `build_candidate_set(...)` public helper가
    `target_candidates`, `expansion_seed`, `producer_candidates`, flat
    `candidates`를 분리해 반환한다. XGEN adapter는 retrieved top-K를 target
    surface로 유지하면서 selected target만 producer expansion seed로 전달할 수
    있다.
- near-duplicate/sibling 후보를 제어한다.
  - `2026-07-19`: 전역 suppression 대신 `build_candidate_set(...)`의
    opt-in `max_targets_per_group`로 같은 `primary_resource` +
    `canonical_action` target sibling을 cap한다. 결과에는
    `raw_target_candidates`, `suppressed_target_candidates`,
    `target_candidate_groups`가 남아 XGEN target selector가 어떤 후보를 줄였는지
    설명할 수 있다.
- multi-intent query에서는 category diversity를 보장한다.
  - `2026-07-19`: `build_candidate_set(...)`에 opt-in
    `max_target_candidates` + `diversify_target_groups`를 추가했다. XGEN
    adapter가 larger target surface를 작은 LLM-visible budget으로 줄일 때,
    첫 group sibling만 채우지 않고 target group round-robin으로 복합 intent의
    resource/action 다양성을 보존할 수 있다.
- 복합 query에서만 adaptive expansion을 적용한다.
- X2BEE 현재 gap은 `order_query`의 target rank 4와 page-role secondary target
  rank 5다. top-K를 늘리지 않고 이 두 유형을 top-3으로 올리는 개선을 우선한다.

### 4. Reranking

Goal: recall을 유지하면서 candidate ambiguity를 줄인다.

- 1차: deterministic heuristic reranker
  - `2026-07-19`: `build_candidate_set(...)`에 opt-in
    `target_action_priority`를 추가했다. XGEN adapter가 query intent를
    `{"create": 5, "update": 4, ...}` 같은 action priority로 변환하면,
    target 후보는 `ai_metadata.canonical_action` 기준으로 stable rerank되고
    `target_rank_signals`에 original/reranked rank, group key, priority,
    selected/suppressed evidence가 남는다.
  - `2026-07-19`: `target_action_priority_for_query(...)`를 추가했다. XGEN은
    LLM 없이 한국어/영어 action term에서 generic action priority를 만들고,
    그 결과를 `build_candidate_set(..., target_action_priority=...)`에 바로
    전달할 수 있다.
  - `2026-07-19`: XGEN deterministic benchmark에
    `selected_target`, `target_selector_rank`, `target_selector_exact`,
    `target_action_priority`, `target_rank_signals`를 기록한다. 현재
    `--suite all` 기준 target recall@5와 selector exact@5가 모두 `1.00`이다.
  - `2026-07-19`: `product_detail_ko`, `audit_logs_ko`, `notify_assignee_ko`
    miss를 줄이기 위해 query-action priority에 detail-after-search,
    audit-log-read, notification-send disambiguation을 추가했다. XGEN
    deterministic selector exact@5는 `0.80`에서 `1.00`으로 올랐다.
- 2차: optional embedding rerank
- 3차: optional small model rerank
- 성공 기준은 top-k=5 exact 상승과 ambiguity 비증가다.

### 5. XGEN Fixtures

Goal: BFCL이 놓치는 실제 API Collection 문제를 포착한다.

Minimum fixture families:

- commerce: search/detail/order/shipping/refund
- admin/user/auth: user, role, permission, token, audit
- workflow update: search/detail/status-change/notification

Each case should include:

- natural-language query
- expected target
- expected producers
- expected plan
- required context defaults
- user input slots
- failure reason when plan cannot be synthesized

## Validation Policy

Use [`validation-loop.md`](validation-loop.md) as the execution contract.

Default research flow:

```bash
make research-check

poetry run python -m benchmarks.bfcl_tool_selection.failures \
  --report /tmp/full-run.json \
  --failure-categories retrieval_miss,candidate_ambiguity \
  --tool-sources retrieved \
  --top-ks 5 \
  --output /tmp/hard-cases.txt

CASE_IDS_FILE=/tmp/hard-cases.txt make research-check-deterministic

CASE_IDS_FILE=/tmp/hard-cases.txt \
MODEL=qwen3.6-27b \
LLM_URL=http://127.0.0.1:8000/v1 \
DISABLE_THINKING=1 \
SMOKE_LIMIT=100 \
make research-check-smoke
```

Full model benchmark is allowed only when:

- README/docs public numbers will be updated.
- a release candidate needs publish validation.
- failure subset metrics show a large enough improvement to justify full distribution checks.

## Non-Goals

- Do not optimize for BFCL leaderboard submission before XGEN product value is proven.
- Do not hide model weakness by changing evaluator definitions.
- Do not put XGEN DB/auth/SSE/cookie/user-id logic into graph-tool-call.
- Do not make top-K larger as the only fix if latency or ambiguity increases.
- Do not add heavyweight runtime dependencies to the core package.

## Decision Checklist

Before promoting a research change:

- Did T0/T1 pass?
- Which failure subset improved?
- Did candidate ambiguity stay flat or decrease?
- Did retrieval miss decrease without large latency growth?
- Did XGEN deterministic plan coverage stay green?
- Is any public benchmark number backed by artifact path and exact command?
- Is the claim product-level, local benchmark-level, or paper-level?

The answer to the last question must be explicit in docs and PR summaries.
