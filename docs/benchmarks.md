# Benchmark Results

Detailed benchmark data for graph-tool-call. The README contains a 3-row summary; this document contains the full pipeline, retrieval-only, competitive, large-scale, and LangChain agent results.

- **Model used (LLM benchmarks)**: `qwen3:4b` (4-bit, Ollama), unless noted
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
```

See [`benchmarks/`](../benchmarks/) for dataset definitions, ground truth, and the runner source.
