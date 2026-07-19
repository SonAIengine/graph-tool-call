# Benchmark Results

Detailed benchmark data for graph-tool-call. The README contains a 3-row summary; this document contains the full pipeline, retrieval-only, competitive, large-scale, and LangChain agent results.
For XGEN tool graph search goals, see
[`docs/research/xgen-tool-graph-goals.md`](research/xgen-tool-graph-goals.md).
For day-to-day research iteration, follow the tiered loop in
[`docs/research/validation-loop.md`](research/validation-loop.md) before running
expensive full model benchmarks.

- **Model used (LLM benchmarks)**: `qwen3:4b` (4-bit, Ollama), unless noted
- **No-model benchmarks**: retrieval-only, BFCL tool-selection, and XGEN
  deterministic engine checks do not call an LLM; their report shows
  `model=none`.
- **Pipelines compared**: `baseline` (all tools), `retrieve-k3 / k5 / k10`, plus `+ embedding`, `+ ontology`
- **Reproduce**: see [Reproduce](#reproduce) at the bottom

---

## What we measure

graph-tool-call verifies two things.

1. Can performance be **maintained or improved** by giving the LLM only a subset of retrieved tools?
2. Does the **retriever itself** rank the correct tools within the top K?

These are different questions. A retriever that achieves high `Gold Tool Recall@K` does not automatically translate to high end-to-end accuracy — the LLM still has to pick the right tool from the candidate set.

### Metrics

- **End-to-end Accuracy** — did the LLM ultimately succeed in selecting the correct tool / performing the correct workflow?
- **Gold Tool Recall@K** — was the canonical gold tool included in the top K at the retrieval stage?
- **Avg tokens** — average tokens passed to the LLM
- **Token reduction** — token savings vs. baseline

> The two accuracy metrics often diverge. Evaluations that accept **alternative tools** or **equivalent workflows** as correct may show End-to-end Accuracy that doesn't exactly match Gold Tool Recall@K. `baseline` has no retrieval stage, so Gold Tool Recall@K does not apply.

---

## 1. Full pipeline comparison

| Dataset | Tools | Pipeline | End-to-end Accuracy | Gold Tool Recall@K | Avg tokens | Token reduction |
|---|---:|---|---:|---:|---:|---:|
| Petstore | 19 | baseline | 100.0% | — | 1,239 | — |
| Petstore | 19 | retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| Petstore | 19 | retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| Petstore | 19 | retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |
| GitHub | 50 | baseline | 100.0% | — | 3,302 | — |
| GitHub | 50 | retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| GitHub | 50 | retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| GitHub | 50 | retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |
| Mixed MCP | 38 | baseline | 96.7% | — | 2,741 | — |
| Mixed MCP | 38 | retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| Mixed MCP | 38 | retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| Mixed MCP | 38 | retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |
| Kubernetes core/v1 | 248 | baseline | 12.0% | — | 8,192 | — |
| Kubernetes core/v1 | 248 | retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding | 80.0% | 94.0% | 1,728 | 78.9% |
| Kubernetes core/v1 | 248 | retrieve-k5 + ontology | **82.0%** | 96.0% | 1,699 | 79.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding + ontology | **82.0%** | **98.0%** | 1,924 | 76.5% |

### Key insights

- **Small/medium APIs (19~50 tools)** — baseline is already strong. graph-tool-call's main value here is **64~91% token savings** with little accuracy loss.
- **Large APIs (248 tools)** — baseline collapses to **12%** due to context overload. graph-tool-call recovers performance to **78~82%** by narrowing candidates through retrieval. At this scale it's not an optimization — it's closer to a required retrieval layer.
- **`retrieve-k5` is the best default**. Good token/accuracy tradeoff. On large datasets, adding embedding/ontology yields further gains.

---

## 2. Retrieval quality (BM25 + graph only)

The table below measures retrieval quality **before the LLM stage**. Only BM25 + graph traversal — no embedding or ontology.

| Dataset | Tools | Gold Tool Recall@3 | Gold Tool Recall@5 | Gold Tool Recall@10 |
|---|---:|---:|---:|---:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub | 50 | 87.5% | **87.5%** | 92.5% |
| Mixed MCP | 38 | 93.3% | **96.7%** | 100.0% |
| Kubernetes core/v1 | 248 | 82.0% | **91.0%** | 92.0% |

### How to read

- **Gold Tool Recall@K** measures the retriever's ability to include the correct tool in the candidate set, **not** final LLM accuracy.
- On small datasets, `k=5` already achieves high recall.
- On large datasets, increasing `k` raises recall but also increases tokens passed to the LLM — consider both.

### Insights

- **Petstore / Mixed MCP** — `k=5` alone includes nearly all correct tools.
- **GitHub** — there's a recall gap between `k=5` and `k=10`; choose `k=10` if recall matters more than tokens.
- **Kubernetes core/v1** — even with 248 tools, `k=5` already achieves **91.0%** gold recall. The retrieval stage alone compresses the candidate set dramatically while retaining most correct tools.

---

## 3. When do embedding and ontology help?

Comparison on the largest dataset (Kubernetes core/v1, 248 tools), all on top of `retrieve-k5`.

| Pipeline | End-to-end Accuracy | Gold Tool Recall@5 | Interpretation |
|---|---:|---:|---|
| retrieve-k5 | 78.0% | 91.0% | BM25 + graph alone is a strong baseline |
| + embedding | 80.0% | 94.0% | Recovers semantically-similar but differently-worded queries |
| + ontology | **82.0%** | 96.0% | LLM-generated keywords/example queries significantly improve retrieval |
| + embedding + ontology | **82.0%** | **98.0%** | Accuracy maintained, gold recall at its highest |

- **Embedding** compensates for **semantic similarity** that BM25 misses.
- **Ontology** **expands the searchable representation itself** when descriptions are short or non-standard.
- Using both together yields limited extra end-to-end gains, but **gold recall reaches its highest**.

---

## 4. Competitive benchmark (retrieval strategies)

Compared 6 retrieval strategies across 9 datasets (19–1068 tools):

| Strategy | Recall@5 | MRR | Latency |
|---|:---:|:---:|:---:|
| Vector Only (≈bigtool) | 96.8% | 0.897 | 176ms |
| BM25 Only | 91.6% | 0.819 | 1.5ms |
| BM25 + Graph (default) | 91.6% | 0.819 | 14ms |
| Full Pipeline (with embedding) | 96.8% | 0.897 | 172ms |

**Key finding** — without embedding, BM25+Graph achieves 91.6% Recall, competitive with vector search at **65× faster speed**. With embedding enabled, performance matches pure vector search.

---

## 5. Scale test: 1068 tools (GitHub full API)

| Strategy | Recall@5 | MRR | Miss% |
|---|:---:|:---:|:---:|
| Vector Only | 88.0% | 0.761 | 12.0% |
| BM25 + Graph | 78.0% | 0.643 | 22.0% |
| Full Pipeline | 88.0% | 0.761 | 12.0% |

At 1068 tools, baseline (passing all definitions) is impractical due to context size — graph-tool-call provides a working retrieval layer where vector-only and full pipeline tie.

---

## 6. LangChain agent benchmark (200 tools)

End-to-end accuracy when **200 simple tools** are registered and invoked through a LangChain agent.

- **Direct (D)** — all 200 tool definitions passed to the LLM at once
- **Graph (G)** — tools managed via graph-tool-call gateway (search → call, 2 turns)

| Model | D-Acc | G-Acc | D-Turns | G-Turns | D-Tokens | G-Tokens | Savings | D-Time | G-Time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4.1 | 60.0% | 80.0% | 1.0 | 2.0 | 52,587 | 6,639 | 87.4% | 15.5s | 17.6s |
| gpt-5.2 | 60.0% | **100.0%** | 1.0 | 2.0 | 53,645 | 10,508 | 80.4% | 20.5s | 17.1s |
| gpt-5.4 | 60.0% | **100.0%** | 1.0 | 2.0 | 60,035 | 14,049 | 76.6% | 18.2s | 17.0s |
| claude-sonnet-4-20250514 | 100.0% | 100.0% | 1.0 | 2.0 | 196,183 | 17,349 | 91.2% | 58.2s | 49.4s |
| claude-sonnet-4-6 | 100.0% | 100.0% | 1.0 | 2.0 | 198,665 | 20,074 | 89.9% | 67.0s | 69.4s |
| claude-haiku-4-5 | 100.0% | 100.0% | 1.0 | 2.0 | 197,845 | 19,714 | 90.0% | 23.7s | 22.8s |

> Acc = accuracy, Turns = average agent turns, Tokens = total tokens, Savings = token reduction (D→G), Time = wall-clock.

### Key findings

- GPT-series models drop to **60% accuracy** when all 200 tools are passed directly; graph-tool-call recovers to **80–100%**.
- Claude-series models maintain 100% accuracy either way, but graph-tool-call delivers **89–91% token savings**.
- Graph mode adds 1 extra turn (search → call) but total latency stays comparable or decreases thanks to smaller context.
- Across all models, token reduction ranges from **76.6% to 91.2%**.

---

## Reproduce

```bash
# Retrieval quality only (fast, no LLM needed)
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# Pipeline benchmark (LLM comparison)
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline \
  --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# Save baseline and compare across runs
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff

# BFCL official function-calling data as a tool-selection benchmark
make bfcl-benchmark
poetry run python -m benchmarks.bfcl_tool_selection.run \
  --categories simple_python,multiple,parallel,parallel_multiple \
  --top-k 5

# BFCL-compatible model tool-call loop
poetry run python -m benchmarks.bfcl_tool_selection.llm_loop \
  --categories simple_python \
  --limit 5 \
  --tool-source retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking

# Optional official BFCL AST checker path in an isolated venv
uv venv /tmp/gtc-bfcl-eval --python /usr/bin/python3
uv pip install --python /tmp/gtc-bfcl-eval/bin/python \
  bfcl-eval==2025.12.17 soundfile
PYTHONPATH="$PWD" /tmp/gtc-bfcl-eval/bin/python \
  -m benchmarks.bfcl_tool_selection.llm_loop \
  --categories simple_python \
  --limit 5 \
  --tool-source retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking \
  --evaluator official \
  --official-model-name qwen3-32b-FC \
  --cache-dir /tmp/gtc-bfcl-cache \
  --bfcl-result-dir /tmp/gtc-bfcl-results

# Official-checker smoke sweep across sources and top-K values
PYTHONPATH="$PWD" /tmp/gtc-bfcl-eval/bin/python \
  -m benchmarks.bfcl_tool_selection.sweep \
  --categories simple_python,parallel \
  --limit 5 \
  --top-ks 3,5,10 \
  --tool-sources row,retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking \
  --evaluator official \
  --official-model-name qwen3-32b-FC \
  --cache-dir /tmp/gtc-bfcl-cache \
  --concurrency 6 \
  --progress \
  --output /tmp/gtc-bfcl-sweep-smoke.json \
  --bfcl-result-dir /tmp/gtc-bfcl-sweep-results

# Re-score one exported sweep run with the official BFCL CLI.
# The evaluator instantiates the model handler even during offline scoring, so
# qwen/openai-compatible configs may require dummy API keys.
OPENAI_API_KEY=dummy QWEN_API_KEY=dummy /tmp/gtc-bfcl-eval/bin/python \
  -m bfcl_eval evaluate \
  --model qwen3-32b-FC \
  --test-category simple_python \
  --result-dir /tmp/gtc-bfcl-sweep-results/repeat-1/retrieved-k5 \
  --score-dir /tmp/gtc-bfcl-score \
  --partial-eval

# XGEN-style tool graph quality (deterministic, no LLM)
make xgen-benchmark
poetry run python -m benchmarks.xgen_tool_graph.run --json

# XGEN large OpenAPI acceptance (live X2BEE-scale Swagger UI, no LLM)
make xgen-scale-acceptance
poetry run python -m benchmarks.xgen_api_scale.run \
  --output /tmp/gtc-x2bee-scale-acceptance.json

# BFCL-style model-in-the-loop tool search
make xgen-llm-benchmark
poetry run python -m benchmarks.xgen_tool_graph.llm_loop \
  --model qwen3:4b \
  --llm-url http://localhost:11434/api/chat

# Native function-calling Qwen/vLLM endpoint
poetry run python -m benchmarks.xgen_tool_graph.llm_loop \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking
```

See [`benchmarks/`](../benchmarks/) for dataset definitions, ground truth, and the runner source.

## BFCL Official Tool Selection

[`benchmarks/bfcl_tool_selection/`](../benchmarks/bfcl_tool_selection/) converts
the official BFCL v4 function-calling JSONL files into a deterministic
graph-tool-call retrieval benchmark. It uses the BFCL leaderboard checkpoint
commit `f7cf735` by default and downloads the public files from the Gorilla
repository unless `--data-root` points to a local mirror.

This is not the BFCL leaderboard's final AST/function-call score. The official
BFCL score measures whether a model emits the exact function call and arguments.
This benchmark isolates graph-tool-call's layer: it builds one category-wide
function corpus, searches that corpus with each BFCL question, and checks
whether the ground-truth function names appear in the retrieved top-K.

Metrics:

- `recall_at_1/3/5`: fraction of ground-truth function names retrieved.
- `mrr`: reciprocal rank of the first correct function.
- `ndcg_at_5`: ranking quality for the expected function set.
- `all_tools_found_at_5`: whether all required functions for the case are in top-5.
- `argument_schema_coverage`: whether retrieved ground-truth tools expose the
  argument names used by BFCL's possible-answer file.
- `avg_latency_ms`: graph-tool-call retrieval latency per case.

Recommended first pass:

```bash
poetry run python -m benchmarks.bfcl_tool_selection.run \
  --categories simple_python,multiple,parallel,parallel_multiple \
  --top-k 5
```

Verified deterministic result on the default four BFCL single-turn categories
(`simple_python`, `multiple`, `parallel`, `parallel_multiple`):

```text
overall recall@1=0.60 recall@3=0.85 recall@5=0.92
mrr=0.80 ndcg@5=0.81 schema=0.89 latency=2.63ms
simple_python: cases=400 tools=370 recall@5=0.92 all_tools@5=0.92 mrr=0.75
multiple: cases=200 tools=443 recall@5=0.93 all_tools@5=0.93 mrr=0.77
parallel: cases=200 tools=186 recall@5=0.96 all_tools@5=0.96 mrr=0.85
parallel_multiple: cases=200 tools=458 recall@5=0.86 all_tools@5=0.71 mrr=0.87
```

These scores are deterministic retrieval scores over the BFCL function corpus.
They are intentionally separate from the official BFCL model AST score and from
the XGEN-specific Planflow benchmark below.

### BFCL-compatible Model Tool Calls

[`benchmarks/bfcl_tool_selection/llm_loop.py`](../benchmarks/bfcl_tool_selection/llm_loop.py)
adds a native function-calling model loop on top of the same public BFCL v4
files. It has two modes:

- `--tool-source row`: pass the official per-case BFCL tool list to the model.
- `--tool-source retrieved`: first retrieve top-K tools from a category-wide
  graph-tool-call corpus, then pass only those tools to the model.

The second mode is the graph-tool-call integration check. It shows how much of
the model score is lost or preserved when the model sees retrieved candidate
tools instead of the curated per-row BFCL tool list.

Metrics:

- `retrieval_recall_at_k`: whether graph-tool-call retrieved the expected BFCL
  function names.
- `model_tool_call_rate`: whether the model emitted native tool calls.
- `function_name_exact_match`: whether the predicted function-name multiset
  exactly matches BFCL possible answers.
- `argument_name_coverage`: whether expected argument names are present, with
  BFCL optional `""` answers treated as omittable.
- `argument_value_exact_match`: whether function count, names, allowed
  arguments, and allowed values match.
- `strict_exact_match`: function-name exact match plus argument-value exact
  match.

This is BFCL-compatible, not an official leaderboard submission. The local
matcher mirrors the core Python AST-checker behavior for the single-turn
categories used here, including no unexpected arguments, optional `""` values,
and unordered matching for parallel calls. It does not import the official
`bfcl-eval` package or submit model outputs to the BFCL leaderboard harness.

For stricter local validation, the runner also has an optional official checker
path:

```bash
uv venv /tmp/gtc-bfcl-eval --python /usr/bin/python3
uv pip install --python /tmp/gtc-bfcl-eval/bin/python \
  bfcl-eval==2025.12.17 soundfile
PYTHONPATH="$PWD" /tmp/gtc-bfcl-eval/bin/python \
  -m benchmarks.bfcl_tool_selection.llm_loop \
  --categories simple_python \
  --limit 5 \
  --tool-source retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking \
  --evaluator official \
  --official-model-name qwen3-32b-FC \
  --cache-dir /tmp/gtc-bfcl-cache
```

The `--official-model-name` value is the BFCL model config used only for the
official AST checker's function-name conversion rules. It does not change the
served model in `--model`. This is necessary when the actual local/vLLM model
name, such as `qwen3.6-27b`, is not a BFCL leaderboard model key.

Use `--cache-dir` for any model-in-the-loop run beyond a small smoke. The cache
is keyed by case ID, BFCL commit, graph-tool-call version, model, endpoint,
tool source, top-K, evaluator, thinking mode, and optional cache namespace, so
interrupted full sweeps can resume without re-calling the model for completed
cases. Pass `--refresh-cache` only when intentionally replacing previous model
outputs. Use `--cache-namespace` for independent single-run repeats. The sweep
runner automatically uses `repeat-1`, `repeat-2`, and so on when `--repeats` is
greater than one, which prevents later repeats from silently reusing the first
run's case outputs. Use `--concurrency` and `--progress` for full runs; progress
is printed to stderr and records cache hits versus fresh model calls.

Use `--bfcl-result-dir` when the benchmark run should also leave
BFCL-compatible result JSONL files. The single-run CLI writes files below
`<dir>/<official-model-name>/non_live/BFCL_v4_<category>_result.json`; the
sweep CLI writes one such tree per run below
`<dir>/repeat-<n>/<tool-source>-k<k>/`. Each JSONL row contains the BFCL `id`
and `result` fields expected by `bfcl_eval evaluate`, plus graph-tool-call
retrieval metadata for auditability. By default, arguments are exported as
JSON strings (`--bfcl-result-argument-format json-string`), matching the
OpenAI/Qwen FC handlers in `bfcl-eval`.

Use an isolated venv for this path. `bfcl-eval==2025.12.17` pulls a large
benchmark stack and can downgrade packages such as `networkx` and `numpy` if
installed directly into the project Poetry environment. In this local run,
`soundfile` was also needed for `bfcl_eval.constants.model_config` imports.
The official CLI instantiates the selected model handler even for offline
scoring; for qwen/openai-compatible configs, set dummy `OPENAI_API_KEY` and
`QWEN_API_KEY` values if no real API call will be made.

For publish-candidate runs, use the sweep runner instead of hand-running single
commands. It records row-source and retrieved-source results in one JSON
artifact, including `failure_breakdown` counts for retrieval misses, candidate
ambiguity, call-count mismatches, and argument mismatches. When `--repeats` is
greater than one, the JSON `summary.repeat_groups` and text output include
mean/std/min/max for exact match, strict exact match, retrieval recall, and
latency by `(tool_source, top_k)`.

Recommended smoke with a native function-calling endpoint:

```bash
poetry run python -m benchmarks.bfcl_tool_selection.llm_loop \
  --categories simple_python \
  --limit 5 \
  --tool-source retrieved \
  --model qwen3.6-27b \
  --llm-url http://127.0.0.1:8000/v1 \
  --disable-thinking
```

Observed four-category official-checker smoke with `qwen3.6-27b`,
`simple_python,multiple,parallel,parallel_multiple`, `limit=10` each,
`top_k=5`:

```text
row       cases=40 retrieval@K=1.00 exact=0.95 strict=0.90
          failures=call_count_mismatch:2,pass:38
retrieved cases=40 retrieval@K=1.00 exact=0.82 strict=0.78
          failures=call_count_mismatch:3,candidate_ambiguity:4,pass:33

retrieved category breakdown:
simple_python      retrieval@K=1.00 exact=0.90 failures=candidate_ambiguity:1,pass:9
multiple           retrieval@K=1.00 exact=0.90 failures=call_count_mismatch:1,pass:9
parallel           retrieval@K=1.00 exact=0.80 failures=call_count_mismatch:2,pass:8
parallel_multiple  retrieval@K=1.00 exact=0.70 failures=candidate_ambiguity:3,pass:7
```

Observed repeat-safety smoke after adding cache namespaces, with the same model
and four categories, `limit=5`, `tool_source=retrieved`, `top_k=5`,
`repeats=2`. Both repeats made fresh model calls (`cache_hit=0`) and exported
BFCL-compatible result JSONL files that were re-scored by `bfcl_eval evaluate`:

```text
retrieved k=5 repeat=1 cases=20 retrieval@K=1.00 exact=0.85 strict=0.85 latency=3624.9ms
retrieved k=5 repeat=2 cases=20 retrieval@K=1.00 exact=0.85 strict=0.85 latency=3596.2ms
repeat_summary retrieved k=5 repeats=2 exact_mean=0.85 exact_std=0.000 retrieval_mean=1.00 latency_mean=3610.6ms

official CLI category scores per repeat:
simple_python=100.00%, multiple=100.00%, parallel=80.00%, parallel_multiple=60.00%
```

Observed current four-category official-checker retrieved-source top-K sweep,
same model/categories, `limit=10` each:

```text
retrieved k=3  cases=40 retrieval@K=0.93 exact=0.75 failures=call_count_mismatch:2,candidate_ambiguity:3,pass:30,retrieval_miss:5
retrieved k=5  cases=40 retrieval@K=1.00 exact=0.82 failures=call_count_mismatch:3,candidate_ambiguity:4,pass:33
retrieved k=10 cases=40 retrieval@K=1.00 exact=0.80 failures=call_count_mismatch:3,candidate_ambiguity:5,pass:32
```

Category-level retrieved-source view:

```text
retrieved k=3
simple_python      retrieval=1.00 exact=0.90
multiple           retrieval=1.00 exact=1.00
parallel           retrieval=1.00 exact=0.80
parallel_multiple  retrieval=0.70 exact=0.30

retrieved k=5
simple_python      retrieval=1.00 exact=0.90
multiple           retrieval=1.00 exact=0.90
parallel           retrieval=1.00 exact=0.80
parallel_multiple  retrieval=1.00 exact=0.70

retrieved k=10
simple_python      retrieval=1.00 exact=0.80
multiple           retrieval=1.00 exact=0.90
parallel           retrieval=1.00 exact=0.80
parallel_multiple  retrieval=1.00 exact=0.70
```

Current full runs, same model/categories, no `limit`, official checker.
The row-source baseline passes the official per-case BFCL tool list to the
model. The retrieved-source runs pass only graph-tool-call top-K candidates.
The retrieved-source full result export was also re-scored with
`bfcl_eval evaluate --partial-eval`; per-category score JSON files matched the
runner summary for `k=3`, `k=5`, and `k=10`.

```text
row       k=5  cases=1000 retrieval@K=0.91 exact=0.90 strict=0.89
          failures=argument_name_mismatch:35,argument_value_mismatch:32,call_count_mismatch:15,official_checker_mismatch:1,pass:896,retrieval_miss:21

retrieved k=3  cases=1000 retrieval@K=0.84 exact=0.69 strict=0.68
          failures=argument_name_mismatch:23,argument_value_mismatch:38,call_count_mismatch:10,candidate_ambiguity:33,pass:686,retrieval_miss:210
retrieved k=5 cases=1000 retrieval@K=0.92 exact=0.76 strict=0.76
          failures=argument_name_mismatch:22,argument_value_mismatch:36,call_count_mismatch:15,candidate_ambiguity:50,official_checker_mismatch:1,pass:764,retrieval_miss:112
retrieved k=10 cases=1000 retrieval@K=0.96 exact=0.80 strict=0.79
          failures=argument_name_mismatch:21,argument_value_mismatch:39,call_count_mismatch:16,candidate_ambiguity:72,official_checker_mismatch:1,pass:798,retrieval_miss:53

retrieved k=5 repeat=2
          exact_mean=0.764 exact_std=0.000 strict_mean=0.758
          retrieval_mean=0.917 latency_mean=5599.1ms
          official CLI per-repeat category scores:
          simple_python=77.25%, multiple=82.50%, parallel=83.50%, parallel_multiple=61.50%

Full retrieved-source category breakdown:
k=3
simple_python      retrieval@K=0.855 exact=0.728 strict=0.730 failures=candidate_ambiguity:18,pass:291,retrieval_miss:58
multiple           retrieval@K=0.880 exact=0.775 strict=0.760 failures=candidate_ambiguity:4,pass:155,retrieval_miss:24
parallel           retrieval@K=0.930 exact=0.810 strict=0.805 failures=candidate_ambiguity:9,pass:162,retrieval_miss:14
parallel_multiple  retrieval@K=0.677 exact=0.390 strict=0.385 failures=candidate_ambiguity:2,pass:78,retrieval_miss:114

k=5
simple_python      retrieval@K=0.917 exact=0.773 strict=0.773 failures=candidate_ambiguity:25,pass:309,retrieval_miss:33
multiple           retrieval@K=0.930 exact=0.825 strict=0.805 failures=candidate_ambiguity:7,pass:165,retrieval_miss:14
parallel           retrieval@K=0.965 exact=0.835 strict=0.830 failures=candidate_ambiguity:11,pass:167,retrieval_miss:7
parallel_multiple  retrieval@K=0.857 exact=0.615 strict=0.610 failures=candidate_ambiguity:7,official_checker_mismatch:1,pass:123,retrieval_miss:58

k=10
simple_python      retrieval@K=0.963 exact=0.810 strict=0.810 failures=candidate_ambiguity:32,pass:324,retrieval_miss:15
multiple           retrieval@K=0.975 exact=0.845 strict=0.825 failures=candidate_ambiguity:14,pass:169,retrieval_miss:5
parallel           retrieval@K=0.995 exact=0.855 strict=0.850 failures=candidate_ambiguity:11,pass:171,retrieval_miss:1
parallel_multiple  retrieval@K=0.926 exact=0.670 strict=0.665 failures=candidate_ambiguity:15,official_checker_mismatch:1,pass:134,retrieval_miss:32
```

Interpretation: with the official per-row tool list, this model emits correct
native tool calls on most full cases (`exact=0.90`). With graph-tool-call
retrieval in front, the best full retrieved-source run so far is `top_k=10`
with `exact=0.80`, while `top_k=5` is faster but lower at `exact=0.76`. Raising
top-K recovers retrieval recall and reduces retrieval misses, but it also
increases candidate ambiguity and latency. This makes the benchmark useful for
retrieval and candidate-ranking work, but it is not yet a publishable BFCL
leaderboard score.

Current bottleneck: `parallel_multiple` is the weakest category. The full
retrieved run shows 58 retrieval misses in 200 cases at `top_k=5`, and 32
misses even at `top_k=10`, so this is not just a model formatting problem.
Top-K expansion helps retrieval recall, but exact match remains limited by
retrieval misses, candidate ambiguity, and multi-call/count behavior. That makes
multi-intent decomposition, dependency-aware grouping, stronger candidate
evidence, and repeated full runs the next quality targets before a
publish-candidate run. BFCL-compatible result export now exists for local
official-checker reruns; it should be used to keep future numbers tied to
auditable model outputs.

## XGEN-style Tool Graph Search

The XGEN-style benchmark lives in
[`benchmarks/xgen_tool_graph/`](../benchmarks/xgen_tool_graph/). It is inspired
by function-calling benchmark design, but targets the graph-tool-call engine
contract directly: OpenAPI extraction, IO contract construction, Korean query
retrieval, producer expansion, plan synthesis, argument binding, user-input
slots, and trace evidence.

Model used: **none**. This runner is deterministic and reports
`methodology=deterministic_engine_contract`.

It intentionally avoids live HTTP and LLM calls so a PR can prove whether search
quality improved or regressed with deterministic numbers. The default built-in
suite compares `target_only` with `graph_with_producers` and fails when the
graph pipeline misses quality thresholds or exceeds latency/token budgets
recorded in the suite's cases file.

Run the full product-readiness fixture set:

```bash
poetry run python -m benchmarks.xgen_tool_graph.run --suite all
```

Current built-in fixture families:

| Suite | API pattern | Cases |
|---|---|---:|
| `commerce` | search/detail/order/shipping/refund | `6` |
| `admin` | user, role, session, audit | `3` |
| `workflow` | search/current-task/approve/notify/escalate | `3` |

Latest local deterministic suite result on 2026-07-19:

| Metric | Value |
|---|---:|
| Fixture families | `3` |
| Cases | `12` |
| Tools | `22` |
| Graph edges | `35` |
| Target recall@5 | `1.00` |
| Producer recall | `1.00` |
| Candidate plan coverage | `1.00` |
| Plan exact match | `1.00` |
| Binding accuracy | `1.00` |
| Average retrieval latency | `0.22ms` |

### XGEN Scale Acceptance

[`benchmarks/xgen_api_scale/`](../benchmarks/xgen_api_scale/) is the opt-in
large-OpenAPI acceptance check for XGEN. It is separate from the deterministic
fixture above because it hits a live Swagger UI and profiles a real API
collection at X2BEE BO scale.

Default target:

```text
https://api-bo.x2bee.com/api/bo/swagger-ui/index.html
```

Run:

```bash
make xgen-scale-acceptance \
  OUT=/tmp/gtc-x2bee-scale-acceptance.json
```

For development, use the top-K sweep first. It builds the large graph once and
then replays the same Korean cases at multiple K values, so ranking experiments
can be judged without a long model run:

```bash
make xgen-scale-sweep \
  TOP_KS=3,5,10 \
  OUT=/tmp/gtc-x2bee-scale-sweep.json
```

When changing OpenAPI contract extraction or field-ranking policy, run the
contract-signal ablation before any model loop. It loads the live Swagger specs
once, builds two graphs from the same input, and reports promoted-minus-baseline
search deltas:

```bash
make xgen-scale-contract-ablation \
  CONTEXT_FIELDS=siteNo,langCd,sysGbCd \
  OUT=/tmp/gtc-x2bee-scale-contract-ablation.json
```

The promoted variant uses `metadata.api_contract` selectively: wrapper fields
such as `status`, `data`, and `list` stay out of the promoted contract, while
identifier-like response fields, required inputs, enums, context/auth fields,
and search filters can enter `metadata.produces` / `metadata.consumes`.
Promoted raw contract rows are planning/producer signals by default
(`search_signal=False`) so target-tool BM25 ranking is not flooded by common
identifier fields. Use `--index-promoted-contract-fields` only as a diagnostic
or after a collection-specific curation pass.

Latest local contract-signal ablation on 2026-07-19:

| Variant | Hit@10 | Recall@10 | Top-1 | Top-3 | MRR | Avg latency |
|---|---:|---:|---:|---:|---:|---:|
| baseline | `1.00` | `1.00` | `0.75` | `0.875` | `0.823` | `31.77ms` |
| promoted contract, no BM25 field indexing | `1.00` | `1.00` | `0.75` | `0.875` | `0.823` | `28.07ms` |

The same diagnostic previously showed that indexing all promoted raw contract
fields degraded target ranking on X2BEE, which is why the default keeps
contract fields available for planning without adding them directly to BM25.

Verified local result on 2026-07-19:

| Metric | Value |
|---|---:|
| Swagger spec groups | `15` |
| Raw operations | `2,173` |
| Ingested tools | `2,161` |
| Unique tools after operationId dedupe | `1,084` |
| Duplicate tools skipped | `1,077` |
| Graph edges | `8,599` |
| Contract request tools | `2,069` |
| Contract response tools | `1,615` |
| Contract consumes fields | `23,719` |
| Contract produces fields | `38,873` |
| Build time | `4.61s` |
| Korean smoke hit@10 | `8/8` |
| Expected tool recall@10 | `1.00` |
| Top-1 hit@10 | `0.75` |
| Top-3 hit@10 | `0.875` |
| Mean MRR | `0.823` |
| Average retrieval latency | `40.04ms` |

Top-K sweep from the same live target on 2026-07-19:

| Top-K | Hit@K | Expected recall@K | Top-1 hit | Top-3 hit | Mean MRR | Main gap |
|---:|---:|---:|---:|---:|---:|---|
| `3` | `0.75` | `0.8125` | `0.75` | `0.875` | `0.792` | `order_query`, secondary page-role button |
| `5` | `1.00` | `1.00` | `0.75` | `0.875` | `0.823` | rank-4/5 compression |
| `10` | `1.00` | `1.00` | `0.75` | `0.875` | `0.823` | acceptance baseline |

OpenAPI request/response contract is preserved under `metadata.api_contract`
and `metadata.openapi`. It is intentionally not promoted into top-level
`metadata.produces` / `metadata.consumes` during plain OpenAPI ingest; raw
schema leaves are useful for execution and graph construction, but indexing all
of them directly can add noisy common fields to large Swagger search.

This is not a model score. It verifies that graph-tool-call can discover the
Swagger groups, dedupe umbrella/group duplicates, ingest the resulting 1k-tool
collection, build the graph, and retrieve expected tools for Korean BO queries.
Use it before XGEN integration changes and before claiming product-level
readiness.

### BFCL-style LLM Loop

[`benchmarks/xgen_tool_graph/llm_loop.py`](../benchmarks/xgen_tool_graph/llm_loop.py)
uses the same evaluation shape as tool-use benchmarks such as BFCL Web Search:
the model receives a real function, must call it, sees the function result, and
then emits a normalized JSON answer that can be exact-matched.

The exposed function is `search_tools(query)`, backed by graph-tool-call
retrieval and producer expansion. Each case records:

- `search_tool_call_rate`: did the model actually call the search function?
- `search_target_recall_at_k`: did the search result contain the expected target?
- `candidate_plan_coverage`: did the candidate set contain the expected plan tools?
- `final_target_accuracy`: did the model select the expected target?
- `final_plan_exact_match` / `final_plan_step_recall`: did it reconstruct the chain?
- `avg_tool_calls`, tokens, and latency.

Run this with a native function-calling model for the strict benchmark. The
`--protocol prompted` mode is available for diagnosing non-function-calling
models, but native protocol is the BFCL-style score.

Model used: the command's `--model` value. The report prints both `model` and
`protocol`, so model capability is never mixed with deterministic engine scores.

On the current local Ollama smoke model (`qwen3:4b`, Ollama `0.17.7`), the
strict native loop fails with `search_tool_call_rate=0.00`: the model writes
reasoning text but does not emit a `tool_calls` entry. That is a model/tool-call
capability failure. The deterministic engine benchmark above should be used to
judge graph-tool-call search quality; the LLM loop judges whether a selected
model can actually use that search tool.

On `qwen3.6-27b` served by vLLM from `Qwen/Qwen3.6-27B-FP8` with native tool
calling enabled, the strict loop passes when reasoning output is disabled with
`--disable-thinking`:

```text
model=qwen3.6-27b protocol=native disable_thinking=true
search_call=1.00 target@K=1.00 final_target=1.00
plan_exact=0.83 step_recall=0.89 latency=2163.8ms
```

One case (`inventory_chain_ko`) selects the correct final target but omits
upstream producer steps because the wording can be read as "the SKU is already
known." This is counted in `final_plan_exact_match`, while graph-tool-call's
own retrieval and candidate-plan coverage remain `1.00`.
