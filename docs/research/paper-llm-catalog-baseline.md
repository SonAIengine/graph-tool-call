# Budgeted LLM Catalog-Selector Baseline

## Purpose

B0-L answers a necessary comparison question for the paper:

> Under the same per-call catalog budget, can the same LLM search the entire
> tool catalog without graph retrieval and match B6c quality at reasonable
> cost?

A flat catalog cannot fit into one 2,048-token request for the larger sources.
Silently truncating it would create a weak baseline, while giving the LLM an
unlimited context would make cost incomparable. B0-L therefore scans every
tool through deterministic budget-sized chunks and records the additional
model calls, tokens, and latency.

The paired experiment is:

```text
B6c: graph ranking -> 2,048-token selection catalog -> final selection
B0-L: full flat catalog -> hierarchical 2,048-token chunks -> final selection

both -> complete-schema hydration -> same planner -> same structural validator
```

## Frozen B0-L Protocol

The methodology revision is `paired-budgeted-llm-catalog-vs-b6c-v1`.

The flat index is ordered by case-insensitive operation name. Each entry may
contain only per-tool facts:

- exact operation name and bounded source description;
- method and path when the source provides them;
- required and optional input names/types;
- response-field names/types extracted from the source contract;
- flat action, resource, module, and result-shape metadata when available.

The B0-L prompt never receives graph edges, graph expansion, retrieval ranks,
trace-learning evidence, expected targets, required producers, or held-out
labels. This makes it a contract-aware but graph-free catalog selector rather
than an artificially impoverished name-only baseline.

The index is partitioned by
`paper-hierarchical-catalog-chunking-v1`. Every serialized chunk must be at or
below the deterministic artifact's frozen `token_budget.limit`. There is no
cross-chunk packing based on the query.

When the catalog requires multiple chunks:

1. the same model returns at most five local candidates from each chunk, and
   never more than half of that chunk's candidates;
2. local candidates are deduplicated in observed model order;
3. the reduced pool is chunked again under the same budget;
4. reduction repeats until one chunk remains; the half-chunk cap prevents a
   multi-candidate chunk from passing through unchanged;
5. the final call returns one target and at most four supporting tools.

The explicit final cap is frozen as `paper-b0l-final-selection-v1`; post-hoc
truncation is retained only as a protocol-violation guard.

An initial one-chunk catalog goes directly to final selection. Empty output,
invented names, failure to reduce, or exceeding the maximum hierarchy depth
is recorded as a structured selection failure. The first round must expose
100% of source tools. Coverage is computed from the union of names actually
placed in first-round model-facing chunks, not inferred from source size;
otherwise the protocol gate fails.

After selection, both conditions hydrate the selected tools from the same
source snapshot. Both use the B6c model-loop planning prompt, complete schema
hashes, bounded planning contract view, and plan validator. HTTP execution is
not part of this experiment.

## Fairness And Cost

B0-L and B6c use the same:

- train/dev cases and sealed held-out policy;
- model, immutable model revision, tokenizer, decoding settings, and seed;
- per-call catalog token budget;
- maximum final selected-tool count;
- complete-schema hydration, planner, and validation policy.

Condition invocation order is counterbalanced by paired-seed parity so B6c is
not always the cold or warm request. B0-L is allowed more selector calls
because exhaustive catalog coverage is its defining strategy. Independent
chunks within one hierarchy round run with a frozen concurrency of four by
default. The artifact separately records wall latency and the sum of model
response latencies so parallelism reduces experiment duration without hiding
service work. The artifact reports both effectiveness and resource cost:

- selector target accuracy, producer recall, required-tool recall, and E2E
  structural validity;
- catalog chunks and hierarchy rounds;
- maximum per-call catalog tokens and cumulative catalog tokens scanned;
- selector and total model-call counts;
- actual provider input/output tokens and latency.

This supports two useful outcomes. Better B6c quality at comparable cost is
effectiveness evidence. Similar quality with substantially fewer calls or
tokens is efficiency evidence. If B0-L is both cheaper and better, that is a
valid negative result and B6c must be improved before held-out evaluation.

## Run

Generate the deterministic train/dev input first:

```bash
make paper-contract-projection
```

Run a small smoke before the publication candidate:

```bash
poetry run python -m benchmarks.paper_model_loop.llm_catalog_run \
  --baseline-artifact /tmp/graph-tool-call-paper-contract-projection.json \
  --model qwen3.6-27b \
  --model-revision e89b16ebf1988b3d6befa7de50abc2d76f26eb09 \
  --provider openai-compatible \
  --llm-url http://localhost:8000/v1 \
  --limit 3 \
  --repeats 1 \
  --out /tmp/graph-tool-call-paper-b0l-smoke.json
```

After the smoke artifact passes review, run the frozen train/dev comparison:

```bash
BASELINE_ARTIFACT=/tmp/graph-tool-call-paper-contract-projection.json \
MODEL=qwen3.6-27b \
MODEL_REVISION=e89b16ebf1988b3d6befa7de50abc2d76f26eb09 \
PROVIDER=openai-compatible \
LLM_URL=http://localhost:8000/v1 \
REPEATS=3 \
BOOTSTRAP_RESAMPLES=10000 \
make paper-llm-catalog-baseline
```

The endpoint is redacted in the artifact. Prompts contain catalog contracts
but no credentials, environment values, request payloads, or raw reasoning.

## Interpretation Boundary

B0-L is an exhaustive, graph-free catalog-selection baseline under a bounded
per-call context. It is not a zero-cost full-context oracle. It may spend many
more model calls than B6c, and that cost is part of the result.

The train/dev comparison is not a held-out claim. Do not open the test split,
tune the hierarchy using test outcomes, or describe structural plan validity
as HTTP execution success.
