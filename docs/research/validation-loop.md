# Research Validation Loop

graph-tool-call search 연구는 full model benchmark를 매번 돌리면 속도가
무너진다. 이 문서는 XGEN tool graph search 고도화 작업에서 사용할 검증
계층, 실행 명령, artifact 규칙, 승격 기준을 고정한다.

목표와 milestone 기준은 [`xgen-tool-graph-goals.md`](xgen-tool-graph-goals.md)를
따른다. 이 문서는 그 목표를 빠르게 검증하기 위한 실행 루프다.

## 목표

- 일반 검색 로직 수정은 10분 안에 방향성을 판단한다.
- LLM 호출은 마지막 증거로만 사용하고, 대부분의 ranking 실험은 deterministic
  metric으로 거른다.
- full BFCL model run은 release candidate 또는 README 수치 갱신 때만 실행한다.
- 모든 benchmark 주장은 실행 artifact와 재현 명령으로 역추적 가능해야 한다.

## 검증 계층

| Tier | 목적 | 예상 시간 | LLM | 기본 명령 | 사용 시점 |
|---|---|---:|:---:|---|---|
| T0 unit | public contract와 빠른 회귀 | < 1분 | no | `make research-check-unit` | 거의 모든 수정 |
| T1 deterministic | retrieval/graph/plan 품질 확인 | 1-3분 | no | `make research-check` | 검색/graph/fixture 수정 |
| T2 failure subset | 이전 실패 케이스 재검증 | 5-15분 | optional | `CASE_IDS_FILE=/tmp/ids.txt make research-check-smoke` | ranking/rerank 실험 |
| T2.5 XGEN scale | 실제 대형 OpenAPI acceptance/sweep | < 1분 | no | `make xgen-scale-sweep` | XGEN 적용성 판단 |
| T3 model smoke | 소량 실제 tool-call 확인 | 5-15분 | yes | `make research-check-smoke` | 후보 구성이 바뀐 경우 |
| T4 release | publish 후보 검증 | 1-5시간 | yes/manual | `make release-check` + full BFCL commands | README/MR/release |

T0-T1은 매일 자주 돌린다. T2-T3는 실험 branch에서만 선택적으로 돌린다.
T4는 milestone 또는 publish candidate에서만 허용한다.

BFCL model sweep artifact에는 `summary.milestone_gate`가 포함된다. 기본
profile은 `xgen-0.27`이며, retrieved `k=5` exact, retrieval recall, row-source
upper-bound preservation, `parallel_multiple` exact를 한 번에 판정한다. 이 gate가
`fail`이면 full run 숫자를 더 오래 읽지 말고 `failure_breakdown`,
`category_rows`, hard-case bundle로 돌아가 작은 subset을 먼저 고친다. row-source
baseline이나 `parallel_multiple`를 일부러 제외한 smoke에서는 `incomplete`가 정상일
수 있다.

Gate failure가 `retrieval_miss`가 아니라 `candidate_ambiguity` 중심이면
`--retrieval-rank-hints` ablation을 먼저 돌린다. 이 옵션은 retrieved 후보의 tool
description에 graph rank hint만 붙이므로 검색 알고리즘 개선과 LLM-facing 후보
표현 개선을 분리해서 볼 수 있다.

`call_count_mismatch`나 generic helper over-selection이 보이면
`--candidate-selection-guidance` ablation을 별도로 돌린다. 이 옵션은 후보 set을
바꾸지 않고 system prompt의 선택 정책만 강화한다.

`2026-07-19` qwen3.6-27B small smoke artifact:

- baseline: `/tmp/gtc-bfcl-qwen027-smoke-live.json`
- rank-hint ablation: `/tmp/gtc-bfcl-qwen027-rankhint-smoke.json`
- selection-guidance smoke: `/tmp/gtc-bfcl-qwen027-guidance-smoke.json`
- hard cases: `/tmp/gtc-bfcl-qwen027-smoke-hardcases`
- selection-guidance hard cases: `/tmp/gtc-bfcl-qwen027-guidance-hardcases`
- cohesive namespace smoke: `/tmp/gtc-bfcl-qwen027-cohesive-smoke-v2.json`
- cohesive namespace hard cases: `/tmp/gtc-bfcl-qwen027-cohesive-hardcases-v2`

두 smoke 모두 retrieved `k=5` exact `0.85`, retrieval recall `1.00`,
`parallel_multiple` exact `0.60`이다. 즉 다음 작은 subset은 retrieval miss가
아니라 candidate ambiguity와 call-count mismatch를 우선 본다.
Selection guidance를 full 20-case smoke에 적용하면 retrieved exact는
`0.85 -> 0.90`으로 오르고 `parallel_3` call-count mismatch는 pass로 바뀐다.
남은 실패는 `parallel_multiple_2`, `parallel_multiple_4`의 sibling ambiguity 2건이다.
따라서 다음 깊은 개선은 prompt만이 아니라 candidate equivalence/grouping 쪽이다.
Cohesive namespace candidate compression을 selection guidance와 함께 적용하면 같은
20-case smoke에서 retrieved exact는 `0.95`, row-source preservation은 `0.95`,
`parallel_multiple` exact는 `0.80`이 되어 `xgen-0.27` milestone gate가 pass한다.
남은 실패는 `parallel_multiple_4`의 integral sibling ambiguity 1건이다.

같은 옵션을 category별 `limit=25`인 100-case 중간 검증으로 넓히면 작은 smoke의
gate-pass가 아직 전체 분포로 일반화되지는 않는다. `2026-07-19` artifact는
`/tmp/gtc-bfcl-qwen027-cohesive-guard-limit25.json`이고, hard cases는
`/tmp/gtc-bfcl-qwen027-cohesive-guard-limit25-hardcases`에 있다.

```bash
poetry run python -m benchmarks.bfcl_tool_selection.sweep \
  --categories simple_python,multiple,parallel,parallel_multiple \
  --limit 25 \
  --top-ks 5 \
  --tool-sources row,retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:18000/v1 \
  --disable-thinking \
  --candidate-selection-guidance \
  --cohesive-namespace-candidates \
  --cache-dir /tmp/gtc-bfcl-qwen027-cohesive-guard-limit25-cache \
  --concurrency 6 \
  --progress \
  --progress-every 5 \
  --output /tmp/gtc-bfcl-qwen027-cohesive-guard-limit25.json
```

결과는 row-source exact `0.94`, retrieved exact `0.83`, retrieval@5 `0.99`,
row-source preservation `0.883`, `parallel_multiple` exact `0.84`다. 0.27 gate는
retrieved exact와 row preservation 때문에 `fail`이다. 다만 이전 100-case run에서
보이던 `candidate_not_present` 2건은 0건으로 사라졌고, `parallel_multiple` exact는
`0.76 -> 0.84`로 올랐다. 남은 실패 17건은 `candidate_ambiguity:8`,
`argument_value_mismatch:6`, `call_count_mismatch:2`, `retrieval_miss:1`이다.
paired row/retrieved attribution 기준으로 보면 row-source에서는 pass했지만
retrieved-source에서만 fail한 retrieval/presentation 손실은 11건이다.
Breakdown은 `candidate_ambiguity:8`, `argument_value_mismatch:2`,
`retrieval_miss:1`이고, retrieved exact on row-pass cases는 `0.883`이다.
따라서 다음 T2/T3 루프는 후보 누락이 아니라 near-duplicate disambiguation,
argument preservation을 우선 보고, row-source에서도 실패한 repeated-call 문제는
별도 model/tool-schema upper-bound 이슈로 분리한다.

`benchmarks.bfcl_tool_selection.sweep` summary에는
`row_vs_retrieved_deltas`가 들어간다. 같은 repeat/top-K의 row-source와
retrieved-source를 case-id 기준으로 pair해서 `both_pass`,
`row_pass_retrieved_fail`, `row_fail_retrieved_pass`, `both_fail`,
`retrieved_exact_on_row_pass`,
`retrieved_equivalence_adjusted_exact_on_row_pass`,
`row_pass_retrieved_fail_breakdown`, `row_pass_retrieved_fail_tags`,
`row_pass_retrieved_fail_case_ids`를 남긴다. 이 값으로 full/smoke 이후 바로
"검색 계층이 실제로 깎은 케이스"와 "exact name은 틀렸지만 equivalent tool
surface로 맞은 케이스"를 분리한다.

`benchmarks.bfcl_tool_selection.llm_loop`는 graphify의
`build_tool_equivalence_groups(...)`를 사용해 candidate ambiguity 중 tool name,
description, parameter surface가 충분히 가까운 경우
`near_duplicate_tool_surface` failure tag를 붙인다. 같은 100-case artifact를
cache 재사용으로 재요약한
`/tmp/gtc-bfcl-qwen027-cohesive-guard-limit25-equivalence.json` 기준
row-pass/retrieved-fail 11건 중 4건이 이 high-confidence duplicate surface다.
해당 케이스는 `simple_python_6`, `simple_python_12`, `simple_python_21`,
`simple_python_22`이고, 다음 XGEN 쪽 개선은 exact-name 맞춤보다 duplicate
group/equivalence evidence와 selector rerank로 처리한다. 같은 evidence는
`build_candidate_set(...)`의 `target_equivalence_groups`에도 들어간다.
XGEN deterministic artifact도 `target_selector.target_equivalence_groups`,
case-level `target_equivalence_group_count`, summary-level
`avg_target_equivalence_group_count`와 `target_equivalence_group_case_count`를
기록한다. `/tmp/gtc-xgen-equivalence-diagnostics.json` 기준 built-in suite 전체는
평균 equivalence group count `0.333333`, equivalence group case `5`건이다.

`2026-07-19`부터 BFCL model-loop report는
`equivalence_adjusted_exact_match`도 함께 남긴다. 이 값은 기존
`evaluator_exact_match`를 대체하지 않으며, BFCL leaderboard 점수로 사용하지
않는다. strict exact가 실패했더라도 `build_tool_equivalence_groups(...)` 기준
high-confidence equivalent surface이고 argument value가 맞을 때만 별도 credit을
준다. 위 4개 `near_duplicate_tool_surface` subset을 qwen3.6-27B로 재실행한
`/tmp/gtc-bfcl-neardup-adjusted-metric.json` 기준 strict/evaluator exact는
`0.00`, equivalence-adjusted exact는 `1.00`이다.

## 실행 타깃

```bash
make research-check-unit
make research-check-deterministic
make research-check

ARTIFACT_DIR=/tmp/gtc-exp-001 make research-check

MODEL=qwen3.6-27b \
LLM_URL=http://127.0.0.1:8000/v1 \
DISABLE_THINKING=1 \
SMOKE_LIMIT=20 \
ARTIFACT_DIR=/tmp/gtc-exp-001-smoke \
make research-check-smoke
```

`make research-check`는 T1 deterministic tier의 별칭이다. 기본 artifact는
`/tmp/gtc-research-check`에 남는다. XGEN deterministic artifact는
`benchmarks.xgen_tool_graph.run --suite all` 결과이며, commerce/admin/workflow
fixture family를 모두 포함한다. 각 XGEN case의 `synthesis_diagnostics`에는
`stage`, `target`, `selected_producers`, `candidate_signals`, `missing_fields`,
`failure`, `retrieval_evidence`가 남으므로, plan synthesis나 popup/resume 관련
회귀는 이 블록을 먼저 확인한다.

## XGEN Scale Acceptance

XGEN 적용성은 BFCL만으로 판단하지 않는다. XGEN이 실제로 붙을 API Collection은
X2BEE BO처럼 Swagger UI 하나가 여러 OpenAPI group으로 나뉘고, 중복 operation을
포함하며, 한국어 summary와 축약 operationId가 섞인 1천 tool급 문서다.

```bash
make xgen-scale-acceptance \
  OUT=/tmp/gtc-x2bee-scale-acceptance.json

make xgen-scale-sweep \
  TOP_KS=3,5,10 \
  OUT=/tmp/gtc-x2bee-scale-sweep.json

make xgen-scale-contract-ablation \
  CONTEXT_FIELDS=siteNo,langCd,sysGbCd \
  OUT=/tmp/gtc-x2bee-scale-contract-ablation.json
```

`xgen-scale-contract-ablation`은 같은 live spec 로드 결과에서 baseline과
contract-promoted graph를 비교한다. 기본 promoted row는 `search_signal=False`
라서 target search ranking을 오염시키지 않고, producer expansion / plan
synthesis 쪽에서만 쓰인다. raw field를 BM25에도 넣어보는 실험은
`--index-promoted-contract-fields`를 직접 켜서 별도 artifact로 남긴다.

기본 URL은 X2BEE BO Swagger UI다.

```text
https://api-bo.x2bee.com/api/bo/swagger-ui/index.html
```

이 runner는 live spec 본문을 commit하지 않고 실행 시점에 가져온다. report에는
아래를 남긴다.

- discovered spec 수, raw operation 수, unique tool 수, duplicate tool 수
- requestBody/response schema coverage
- graph edge count와 build time
- 한국어 smoke query의 expected tool rank, hit@K, MRR, retrieval latency
- sweep 실행 시 top-K별 hit/recall/top-1/top-3/rank bucket과 missing expected tool

초기 live smoke acceptance 기준선은 `2026-07-19` 실행 기준 다음과 같다.

| Metric | Value |
|---|---:|
| spec groups | `15` |
| raw operations | `2,173` |
| ingested tools | `2,161` |
| unique tools | `1,084` |
| duplicate tools skipped | `1,077` |
| graph edges | `8,599` |
| contract request tools | `2,069` |
| contract response tools | `1,615` |
| contract consumes fields | `23,719` |
| contract produces fields | `38,873` |
| build time | `4.61s` |
| Korean smoke cases | `8/8 hit@10` |
| expected tool recall@10 | `1.00` |
| top-1 hit@10 | `0.75` |
| top-3 hit@10 | `0.875` |
| mean MRR | `0.823` |
| average retrieval latency | `40.04ms` |

top-K sweep 기준선은 다음과 같다.

| Top-K | hit@K | expected recall@K | top-1 hit | top-3 hit | 주요 gap |
|---:|---:|---:|---:|---:|---|
| `3` | `0.75` | `0.8125` | `0.75` | `0.875` | `order_query`, page-role secondary |
| `5` | `1.00` | `1.00` | `0.75` | `0.875` | rank-4/5 압축 |
| `10` | `1.00` | `1.00` | `0.75` | `0.875` | acceptance 기준 |

`2026-07-19` rank-compression branch에서는 같은 live runner를 아래 명령으로
재검증했다.

```bash
make xgen-scale-sweep \
  OUT=/tmp/gtc-x2bee-sweep-after3.json \
  TOP_KS=3,5,10
```

결과는 다음과 같다.

| Top-K | hit@K | expected recall@K | top-1 hit | top-3 hit | mean MRR | 평균 latency |
|---:|---:|---:|---:|---:|---:|---:|
| `3` | `1.00` | `1.00` | `0.75` | `1.00` | `0.833` | `53.39ms` |
| `5` | `1.00` | `1.00` | `0.75` | `1.00` | `0.833` | `23.42ms` |
| `10` | `1.00` | `1.00` | `0.75` | `1.00` | `0.833` | `21.41ms` |

hard case rank 변화는 다음과 같다.

| Case | Before | After |
|---|---|---|
| `order_query_ko` | `getOrderQueryList`: rank `4` at K=5, missing at K=3 | rank `3` at K=3 |
| `page_role_buttons_ko` | secondary page-role target drifted behind user/individual button siblings | `getButtonByPageRoleList`: rank `1`, `getEnabledButtonByPageRoleList`: rank `2` |
| `settlement_compare_ko` | summary target missing at K=5 | list rank `1`, summary rank `2` |
| `return_withdrawal_ko` | `withdrawalReturn`: rank `2` | rank `1` |

이후 X2BEE BO acceptance case set은 smoke 8건에서 product-level 19건으로
확장했다. 추가 도메인은 회원, 마일리지, 이벤트, 상품, 쿠폰, FAQ, 공지,
재입고 알림, 배송비 정책, 프로모션, 기획전이다.

```bash
make xgen-scale-sweep \
  OUT=/tmp/gtc-x2bee-sweep-top1-ambiguity.json \
  TOP_KS=3,5,10
```

19건 product-level sweep 결과는 `hit@3=1.00`, `expected recall@3=1.00`,
`target selector exact@3=1.00`, `top-1 hit=1.00`, `top-3 hit=1.00`,
`mean MRR=1.00`이다. 케이스 기준 rank bucket은 `top_1=19`, `missing=0`이고
selector rank bucket도 `top_1=19`, `missing=0`이다. Tool-name 기준
`rank_buckets`는 `expected_any` 대체 정답까지 모두 세므로 product-level
gate 해석에는 `case_rank_buckets`와 `target_selector_rank_buckets`를 우선한다.
같은 artifact는 contract-based plan readiness도 기록한다. 현재 평균 candidate
count는 `2.16`, 최대 candidate count는 `7`, 평균 producer candidates added는
`1.16`, 평균 required input
coverage는 `0.872`이며 `required_input_not_producible` issue는 `4`건이다.
이 값은 producer-only coverage다. 실행 관점에서는 request wrapper, XGEN
context, user input으로 해결 가능한 required input을 별도 resolution으로 세며,
평균 required input resolution coverage는 `1.00`, unresolved required input
count는 `0`이다. Breakdown은 request wrapper `2`, context input `1`, filter
input `1`이고, resolution breakdown은 producer `42`, request wrapper `2`,
context `1`, user input `1`이다.

raw OpenAPI contract는 `metadata.api_contract`와 `metadata.openapi`에 보존한다.
단, plain ingest에서는 top-level `metadata.produces` / `metadata.consumes`로
자동 승격하지 않는다. 대형 Swagger에서 모든 raw field를 검색 인덱스에 직접
넣으면 `status`, `data`, `list` 같은 공통 field가 노이즈가 되기 때문이다.

이 수치는 live API가 바뀌면 달라질 수 있으므로 public claim으로 쓰기 전에는
artifact 경로와 실행 날짜를 함께 남긴다.

## Failure Subset 루프

full model benchmark 결과에서 실패 케이스를 뽑아 작은 고정 subset으로 만든다.

```bash
poetry run python -m benchmarks.bfcl_tool_selection.failures \
  --report /tmp/gtc-bfcl-full-retrieved-k5-repeats2-current-v7.json \
  --failure-categories retrieval_miss,candidate_ambiguity \
  --tool-sources retrieved \
  --top-ks 5 \
  --output /tmp/gtc-bfcl-k5-hard-cases.txt
```

그 다음 같은 report를 inspector로 읽어서 정답 tool의 현재 rank와 distractor를
확인한다. 이 단계는 LLM을 호출하지 않으며, 알고리즘 수정 전에 실패 원인을
개발 단위로 쪼개기 위한 것이다.

```bash
make bfcl-inspect-failures \
  REPORT=/tmp/gtc-bfcl-full-retrieved-k5-repeats2-current-v7.json \
  OUT=/tmp/gtc-bfcl-k5-hard-cases-inspect.json
```

두 단계를 매번 손으로 이어붙이지 않기 위해 hard-case bundle runner를 기본
진입점으로 둔다.

```bash
make bfcl-hard-cases \
  REPORT=/tmp/gtc-research-check/bfcl-deterministic.json \
  OUT_DIR=/tmp/gtc-bfcl-deterministic-hard-cases \
  FAILURE_CATEGORIES=retrieval_miss \
  REPORT_TOP_KS=5 \
  TOP_K=5 \
  INSPECT_DEPTH=20

make bfcl-hard-cases \
  REPORT=/tmp/gtc-bfcl-full-retrieved-k5-repeats2-current-v7.json \
  OUT_DIR=/tmp/gtc-bfcl-k5-hard-cases \
  FAILURE_CATEGORIES=retrieval_miss,candidate_ambiguity \
  TOOL_SOURCES=retrieved \
  REPORT_TOP_KS=5 \
  TOP_K=5 \
  INSPECT_DEPTH=20
```

첫 번째 명령은 `make research-check`가 남긴 no-LLM deterministic BFCL artifact에서
`recall_at_5 < 1.0` 또는 `all_tools_found_at_5 < 1.0`인 케이스를
`retrieval_miss`로 추론한다. 두 번째 명령은 LLM/sweep report의 명시적
`failure_category`를 사용한다.

이 명령은 `/tmp/gtc-bfcl-k5-hard-cases/` 아래에 다음 파일을 남긴다.

- `case_ids.txt`: deterministic/model smoke에 바로 넣는 전체 hard-case subset
- `cases.json`: failure extractor 결과와 case metadata
- `inspect.json`: deterministic rank/distractor/evidence 진단
- `summary.json`: near-miss, partial multi-tool, weak keyword, outside-depth 요약
- `failure_<category>.txt`: failure category별 case-id subset
- `tag_<tag>.txt`: `near_duplicate_tool_surface` 같은 model-loop failure tag별 subset
- `issue_<issue>.txt`: `expected_present_below_top_k`,
  `partial_multi_tool_at_k`, `weak_or_missing_keyword_signal` 같은 issue별 subset

생성되는 JSON은 케이스별로 아래 정보를 남긴다.

- `expected[].rank`: 정답 tool이 deeper retrieval에서 발견된 순위
- `missing_at_k`, `missing_at_depth`: top-K 또는 inspect depth에서도 빠진 정답
- `distractors`: top-K에서 정답을 밀어낸 후보와 score breakdown
- `issues`: `expected_present_below_top_k`, `weak_or_missing_keyword_signal`,
  `partial_multi_tool_at_k` 같은 개선 대상 분류
- `failure_tags`: `near_duplicate_tool_surface` 같은 LLM/evaluator failure 원인 tag

그 subset만 deterministic으로 먼저 본다.

```bash
CASE_IDS_FILE=/tmp/gtc-bfcl-k5-hard-cases.txt \
BFCL_MIN_RECALL_AT_5=0 \
ARTIFACT_DIR=/tmp/gtc-hardcase-det \
make research-check-deterministic
```

후보 품질이 좋아졌을 때만 실제 model smoke를 돌린다.

```bash
CASE_IDS_FILE=/tmp/gtc-bfcl-k5-hard-cases.txt \
MODEL=qwen3.6-27b \
LLM_URL=http://127.0.0.1:8000/v1 \
DISABLE_THINKING=1 \
SMOKE_LIMIT=100 \
ARTIFACT_DIR=/tmp/gtc-hardcase-smoke \
make research-check-smoke
```

이 흐름의 목적은 full 1000-case run을 반복하지 않고, 이전 병목에 직접 닿는
100-200개 케이스로 변화량을 먼저 확인하는 것이다.

`2026-07-19` BFCL deterministic miss subset에서는 `recall_at_5 < 1`인 97건과
그중 `parallel_multiple` 49건을 별도 case-id 파일로 뽑아 inspector를 돌렸다.

```bash
CASE_IDS_FILE=/tmp/gtc-bfcl-det-miss-parallel-multiple.txt \
BFCL_CATEGORIES=parallel_multiple \
BFCL_MIN_RECALL_AT_5=0 \
ARTIFACT_DIR=/tmp/gtc-pm-clause-test \
make research-check-deterministic

BFCL_MIN_RECALL_AT_5=0 \
ARTIFACT_DIR=/tmp/gtc-clause-conditional-full \
make research-check-deterministic
```

진단 결과는 다음과 같다.

- 전체 deterministic miss 97건 중 73건은 expected tool이 top-20에는 있었고
  top-5 밖에 있는 near-miss였다.
- `parallel_multiple` miss 49건 중 39건은 near-miss였고, 41건은 일부 expected
  tool만 top-5에 있는 `partial_multi_tool_at_k`였다.
- 조건부 `and + action` clause split은 `parallel_multiple_21`의 `data_loading`
  rank를 top-5 안으로 당겼고, 전체 BFCL deterministic 기준 `recall@5`
  `0.929 -> 0.9295`, `all_tools_found@5` `0.903 -> 0.904`,
  `parallel_multiple recall@5` `0.885 -> 0.8875`로 개선했다. 악화 케이스는 0건이다.
- 더 공격적인 clause top-5 확장은 개선 5건/악화 2건으로, 다음 단계에서는
  clause-level diversity 또는 sibling suppression과 함께 재실험한다.

후속 실험에서는 clause가 3개 이상인 명시적 복합 요청에만 clause 후보 depth를
5로 넓히고, `geographic distance`처럼 자연어와 operationId가 어긋나는
BFCL 수학/지리 표현을 keyword scorer에 보강했다. 비교 기준은
`origin/codex/bfcl-clause-expansion`이며, artifact는
`/tmp/gtc-clause-expansion-base/bfcl-deterministic.json`,
`/tmp/gtc-research-check/bfcl-deterministic.json`,
`/tmp/gtc-x2bee-sweep-clause-diversity.json`이다.

- 전체 BFCL deterministic 기준 `recall@5`는 `0.9295 -> 0.9325`,
  `all_tools_found@5`는 `0.904 -> 0.908`, `ndcg@5`는
  `0.8316 -> 0.832768`로 올랐다.
- `parallel_multiple recall@5`는 `0.8875 -> 0.8925`,
  `parallel all_tools_found@5`는 `0.95 -> 0.96`,
  `parallel_multiple all_tools_found@5`는 `0.76 -> 0.77`로 개선했다.
- 케이스 단위 recall 개선은 4건
  (`parallel_69`, `parallel_135`, `parallel_multiple_62`,
  `parallel_multiple_112`)이고, recall 악화 케이스는 0건이다.
- `mrr`은 `0.814133 -> 0.813833`으로 미세하게 낮아졌다. 이 변경은
  top-1 정밀도 개선이 아니라 복합 요청에서 expected tool을 top-5 안에 더
  안정적으로 넣는 recall/diversity 개선으로 본다.
- X2BEE BO Swagger scale sweep은 1084개 unique tool 기준 `hit@3=1.00`,
  `expected recall@3=1.00`, `target selector exact@3=1.00`, `top3=1.00`,
  `mrr=0.83`으로 회귀 없이 통과했다. Scale plan-readiness gate는
  `avg_required_input_coverage >= 0.85`, `avg_candidate_count <= 3`,
  `max_candidate_count <= 8`,
  `avg_required_input_resolution_coverage >= 1.0`,
  `unresolved_required_input_count <= 0` 기준을 추가로 확인한다.
- 전역 sibling suppression은 `parallel_multiple_195` 일부를 개선했지만
  악화 케이스가 크게 늘어 폐기했다. sibling/alias 보정은 앞으로도 broad rule이
  아니라 query/operation evidence가 강한 좁은 규칙으로만 승격한다.

후속 hard-case bundle 실험에서는 deterministic artifact를 먼저 고정한 뒤
`weak_or_missing_keyword_signal` subset을 대상으로 도메인 alias query expansion을
좁게 추가했다. 비교 artifact는 `/tmp/gtc-bfcl-lift-baseline/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-lift-current-guarded2/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-lift-hardcases/inspect.json`,
`/tmp/gtc-bfcl-lift-current-hardcases/inspect.json`이다.

- weak-keyword subset 9건 기준 `recall@5`는 `0.037 -> 0.593`,
  `all_tools_found@5`는 `0.000 -> 0.556`으로 올랐다.
- 전체 BFCL deterministic 기준 `recall@5`는 `0.9325 -> 0.94025`,
  `all_tools_found@5`는 `0.908 -> 0.917`, `mrr`은 `0.8138 -> 0.8212`,
  `ndcg@5`는 `0.8328 -> 0.8406`으로 올랐다.
- Deterministic hard-case count는 `92 -> 83`, `weak_or_missing_keyword_signal`
  issue는 `9 -> 2`로 줄었다.
- X2BEE BO scale acceptance는 1084개 unique tool 기준 `hit@3=1.00`,
  `target selector exact@3=1.00`, `avg_candidate_count=2.16`, `max_candidate_count=7`
  로 통과했다.
- 악화 케이스 2건은 currency sibling exact-name 차이였고, broad
  card/unit alias는 guard로 제한했다. 다음 단계에서는 synonym expansion보다
  sibling-aware target selection 또는 equivalence grouping으로 다룬다.

그 다음 partial multi-tool hard case에서는 broad sibling suppression 대신
actionable clause diversity gate를 추가했다. 배경 설명이나 같은 tool의 반복
argument clause는 기존 보수적인 clause injection을 유지하고, traffic/distance/weather
처럼 서로 다른 actionable sub-task signature가 3개 이상 보일 때만 clause 후보를
top-K 경계 위로 조금 더 보존한다. 비교 artifact는
`/tmp/gtc-bfcl-lift-current-final2/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-partial-diversity-current/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-lift-current-final2-hardcases/inspect.json`,
`/tmp/gtc-bfcl-partial-diversity-hardcases/inspect.json`이다.

- `partial_multi_tool_at_k` subset 38건 기준 `recall@5`는
  `0.535 -> 0.575`, `all_tools_found@5`는 `0.000 -> 0.053`으로 올랐다.
- `expected_present_below_top_k` subset 69건 기준 `recall@5`는
  `0.268 -> 0.290`, `all_tools_found@5`는 `0.000 -> 0.029`로 올랐다.
- 전체 BFCL deterministic 기준 `recall@5`는 `0.94025 -> 0.94200`,
  `all_tools_found@5`는 `0.917 -> 0.920`, `mrr`은
  `0.8212 -> 0.8217`, `ndcg@5`는 `0.8406 -> 0.8421`로 올랐다.
- Deterministic hard-case count는 `83 -> 80`,
  `partial_multi_tool_at_k` issue는 `38 -> 36`으로 줄었다.
- 케이스 단위 recall 개선은 6건, recall 악화 케이스는 0건이었다.
- X2BEE BO scale acceptance는 1084개 unique tool 기준 `hit@3=1.00`,
  `target selector exact@3=1.00`, `avg_candidate_count=2.16`,
  `max_candidate_count=7`로 통과했다.

이어진 near-miss ranking 실험에서는 broad stopword 확장 대신 고신뢰
semantic phrase boost만 추가했다. 대상은 `genetically similar -> genetic
similarity`, `population density`, `highest common factor`, `magnetic field`
with current/distance, lawyer specialization, instrument availability, grocery
store criteria, state/year historical population, public preference 같은
사용자 표현과 tool description이 동시에 맞는 경우다. 비교 artifact는
`/tmp/gtc-bfcl-partial-diversity-current/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-near-miss-current/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-partial-diversity-hardcases/inspect.json`,
`/tmp/gtc-bfcl-near-miss-hardcases/inspect.json`이다.

- 전체 BFCL deterministic 기준 `recall@5`는 `0.94200 -> 0.95000`,
  `all_tools_found@5`는 `0.920 -> 0.928`, `mrr`은
  `0.8217 -> 0.8305`, `ndcg@5`는 `0.8421 -> 0.8509`로 올랐다.
- Deterministic hard-case count는 `80 -> 72`, `expected_present_below_top_k`
  issue는 `67 -> 59`로 줄었다.
- 케이스 단위 recall 개선은 8건, recall 악화 케이스는 0건이었다.
- X2BEE BO scale acceptance는 1084개 unique tool 기준 `hit@3=1.00`,
  `target selector exact@3=1.00`, `avg_candidate_count=2.16`,
  `max_candidate_count=7`, `avg_latency=41.81ms`로 통과했다.

마지막 tail hard-case 실험에서는 `population density` query가 sparse
`calculate_density` operation name만 가지고도 잡히도록 좁은 name fallback을
추가했다. BFCL corpus에는 같은 operation name의 서로 다른 schema가 반복되어
description이 population-specific하지 않은 경우가 있어, XGEN의 짧거나 부실한
operation summary 문제와 같은 형태로 본다. 비교 artifact는
`/tmp/gtc-bfcl-near-miss-current/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-tail-current/bfcl-deterministic.json`,
`/tmp/gtc-bfcl-near-miss-hardcases/inspect.json`,
`/tmp/gtc-bfcl-tail-hardcases/inspect.json`이다.

- 전체 BFCL deterministic 기준 `recall@5`는 `0.95000 -> 0.95200`,
  `all_tools_found@5`는 `0.928 -> 0.930`, `mrr`은
  `0.8305 -> 0.8325`, `ndcg@5`는 `0.8509 -> 0.8529`로 올랐다.
- Deterministic hard-case count는 `72 -> 70`, `expected_present_below_top_k`
  issue는 `59 -> 57`로 줄어 0.26 retrieval-miss gate인 `<= 70`에 도달했다.
- 케이스 단위 recall 개선은 2건, recall 악화 케이스는 0건이었다.
- X2BEE BO scale acceptance는 1084개 unique tool 기준 `hit@3=1.00`,
  `target selector exact@3=1.00`, `avg_candidate_count=2.16`,
  `max_candidate_count=7`, `avg_latency=39.50ms`로 통과했다.

## 승격 기준

연구 변경은 아래 순서로 승격한다.

1. T0 통과: 코드 계약, public import, benchmark runner가 깨지지 않아야 한다.
2. T1 통과: deterministic BFCL recall@5가 기본 threshold 아래로 떨어지면 중단한다.
3. T2 통과: targeted failure subset에서 개선이 보이거나, 악화 이유가 설명 가능해야 한다.
4. T3 통과: 실제 model smoke에서 candidate ambiguity가 과도하게 늘지 않아야 한다.
5. T4 통과: release candidate에서 full run, repeat, official re-score, CI green을 확인한다.

기본 threshold:

- BFCL deterministic recall@5: `>= 0.90`
- XGEN deterministic `graph_with_producers` status: `pass`
- quick contract tests: all pass
- release candidate: `make release-check` + GitHub CI matrix green

## 의사결정 규칙

- 단일 query 개선 때문에 full aggregate가 떨어지면 merge하지 않는다.
- top-K를 올려 recall만 높이고 latency/candidate ambiguity를 크게 늘리는 변경은
  기본값으로 승격하지 않는다.
- LLM smoke 결과가 나빠졌지만 deterministic metric이 좋아진 경우, model prompt
  또는 candidate formatting 문제로 분리해서 기록한다.
- README에 숫자를 갱신할 때는 full run, repeat, BFCL-compatible JSONL export,
  official `bfcl_eval evaluate --partial-eval` 재채점을 같이 남긴다.

## Artifact 규칙

권장 경로:

```text
/tmp/gtc-exp-<short-name>/
  xgen-deterministic.json
  bfcl-deterministic.json
  xgen-llm-smoke.json
  bfcl-llm-smoke.json
  bfcl-cache/
```

commit에는 대형 benchmark artifact를 넣지 않는다. README/docs에는 재현 명령과
요약 수치만 남긴다.

## Full Benchmark 사용 조건

full BFCL model benchmark는 아래 중 하나일 때만 실행한다.

- README/docs의 공개 수치를 갱신한다.
- release candidate를 publish 전에 검증한다.
- deterministic/failure subset에서 큰 개선이 확인되어 전체 분포 영향이 필요하다.
- XGEN 적용 전, 실제 운영 경로의 regression risk를 마지막으로 확인한다.

평상시 검색 로직 실험에서는 full `k=3/5/10`, repeat, official re-score를 돌리지
않는다. 먼저 failure subset과 smoke로 후보를 좁힌다.
