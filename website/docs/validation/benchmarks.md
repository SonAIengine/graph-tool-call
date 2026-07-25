---
title: Benchmarks
description: Measure retrieval, selection, planning, and context reduction quality.
---

# Benchmarks

Benchmarks answer one question: did a change make tool discovery and execution
quality better, worse, or merely different?

Use deterministic suites for daily development and reserve long LLM-backed runs
for release candidates or public claims.

## What To Measure

| Metric | Stage | Meaning |
| --- | --- | --- |
| `hit@k` | retrieval | Expected target appears in the top K candidates |
| `top1` | retrieval | Expected target is ranked first |
| `mrr` | retrieval | Mean reciprocal rank of expected target |
| `ndcg` | retrieval | Rank quality when multiple targets are relevant |
| `candidate_count` | retrieval | Number of tools passed downstream |
| `context_reduction` | retrieval | Schema/context bytes removed before the LLM |
| `selector_accuracy` | target selection | Final selected target matches expectation |
| `plan_hit_rate` | plan | Synthesized plan matches expected target/path |
| `execute_success_rate` | execute | Safe execution cases reach expected result |
| `failure_reason_coverage` | execute | Failures are classified with stable reason codes |
| `latency_ms` | all | Time by stage |

## Development Loop

Run small suites while editing retrieval, graphify, plan, or learning code:

```bash
make quick
```

When the change only affects documentation or website code, use the website
build instead:

```bash
cd website
npm run typecheck
npm run build
```

## Deterministic Benchmark

The repository includes benchmark utilities under `benchmarks/`.

```bash
python -m benchmarks.run_benchmark
```

Store result JSON when the numbers will be referenced in a PR, README, or docs
page.

```bash
python -m benchmarks.run_benchmark \
  --output benchmarks/results/my_run.json
```

## XGEN-Scale Snapshot

Use snapshot replay for large OpenAPI catalog regressions without paying the
cost of a live API or full LLM run.

```bash
make xgen-scale-snapshot
```

Track these gates for large enterprise API catalogs:

- semantic action/resource/module coverage
- search hit@8 and Top-1
- target selector accuracy
- average and max candidate count
- schema context reduction
- uncaught error count

## LLM-Backed Evaluation

LLM-backed runs should record:

| Field | Why It Matters |
| --- | --- |
| model/provider | Results are model-dependent |
| prompt/template version | Target selection can change with prompt shape |
| dataset version | Prevents comparing different test sets |
| graph-tool-call version | Ties result to library behavior |
| seed/config | Helps rerun the same scenario |
| raw result artifact | Allows later inspection |

Do not update public quality claims from a private, one-off, uncommitted run.

## Interpreting Results

| Symptom | Likely Cause | Next Check |
| --- | --- | --- |
| Hit@8 improves but Top-1 drops | Recall widened but ranking got noisier | score breakdown and selector signals |
| Search passes but plan fails | Contract fields or user slots are weak | `api_contract`, `user_input_slots` |
| Plan passes but execute fails | Adapter/auth/runtime issue | `auth_readiness`, runner events |
| Candidate count grows | Graph expansion is too broad | producer expansion and edge evidence |
| Context reduction drops | Too many raw schema leaves are included | artifact text rendering policy |

## Related Pages

- [Quality Lab](./quality-lab.md)
- [XGEN Scale Gates](./xgen-scale-gates.md)
- [BFCL-Style Evaluation](./bfcl-style-evaluation.md)
- [Release Gates](./release-gates.md)
