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
| T3 model smoke | 소량 실제 tool-call 확인 | 5-15분 | yes | `make research-check-smoke` | 후보 구성이 바뀐 경우 |
| T4 release | publish 후보 검증 | 1-5시간 | yes/manual | `make release-check` + full BFCL commands | README/MR/release |

T0-T1은 매일 자주 돌린다. T2-T3는 실험 branch에서만 선택적으로 돌린다.
T4는 milestone 또는 publish candidate에서만 허용한다.

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
`/tmp/gtc-research-check`에 남는다.

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

생성되는 JSON은 케이스별로 아래 정보를 남긴다.

- `expected[].rank`: 정답 tool이 deeper retrieval에서 발견된 순위
- `missing_at_k`, `missing_at_depth`: top-K 또는 inspect depth에서도 빠진 정답
- `distractors`: top-K에서 정답을 밀어낸 후보와 score breakdown
- `issues`: `expected_present_below_top_k`, `weak_or_missing_keyword_signal`,
  `partial_multi_tool_at_k` 같은 개선 대상 분류

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
