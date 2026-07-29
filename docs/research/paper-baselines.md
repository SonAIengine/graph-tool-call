# Frozen Paper Retrieval Baselines

The unified paper harness implements three deterministic development
comparators:

| ID | Artifact key | Frozen behavior |
|---|---|---|
| B-1 | `seeded_random` | Per-case seeded sampling from sorted tool names |
| B0-O | `oracle` | Annotated targets, required producers, then alternatives |
| B1 | `bm25` | BM25 over tool name, one-line summary, and description |

These baselines are research comparators, not product retrieval modes. They
deliberately avoid graph-tool-call semantic expansion, contract scoring,
target selection, and graph evidence.

## Run

```bash
make paper-baseline-run

TOP_K=8 SEED=17 OUT=/tmp/paper-baselines-k8.json \
  make paper-baseline-run
```

The default run uses only the frozen `train,dev` families. It produces one
schema-v1 experiment artifact with paired results for every query:

```bash
poetry run python -m benchmarks.experiment.cli validate \
  /tmp/graph-tool-call-paper-baselines.json
```

## Frozen Contracts

### B-1 Seeded Random

Candidate names are deduplicated and sorted. Each case receives an independent
PRNG seed derived from:

```text
sha256(global_seed:source_id:case_id)
```

This makes the result independent of source iteration and test execution
order.

### B0-O Oracle

The oracle orders available annotated tools as:

1. expected targets;
2. required producers;
3. acceptable alternatives.

It stops at `K` and does not fill the remaining budget with distractors.
Therefore it is a post-retrieval ceiling, not a latency or context-cost
comparator.

### B1 Fixed BM25

The fixed baseline uses `k1=1.2`, `b=0.75`, and tokenizer revision
`paper-bm25-lexical-v1`. Its document contains exactly:

```text
tool.name
metadata.ai_metadata.one_line_summary
tool.description
```

The tokenizer splits identifier boundaries, lowercases Unicode words, and
emits Korean character bigrams for tokens longer than two characters. It does
not stem, use parameters, paths, contracts, graph edges, query expansion,
phrase boosts, or graph-tool-call's production BM25 scorer. Ties are resolved
by case-folded tool name and then the original name.

## Metrics And Budget

Every query records target Hit@K, producer Recall@K, required-tool Recall@K,
all-required-found, Precision@K, MRR, AP, graded nDCG@K, latency, candidate
count, normalized model-facing schema characters, and UTF-8 bytes. The
model-facing schema size includes name, description, and parameters but excludes
internal metadata. Relevance grades are:

- expected target: `3`;
- required producer: `2`;
- acceptable alternative: `1`.

Aggregate producer recall is computed only over cases that annotate required
producers. Bootstrap 95% confidence intervals use 1,000 deterministic
resamples.

The current development gate equalizes the maximum candidate count (`K`).
It records schema size for transparency but does **not** claim equal token
budget: B0-O may return fewer candidates and different tools have different
schema sizes. Publication comparisons requiring context fairness remain
blocked until an actual tokenizer and token-budget truncation policy are
frozen.

## Held-Out Protection

The runner rejects the `test` split unless both conditions hold:

1. `--allow-held-out` is explicitly supplied;
2. the corpus validator reports `paper_ready=true`.

The second condition currently remains blocked by the independent human review
gate. Train/dev development cannot silently open the held-out family.

## Result Status

Artifacts generated from a dirty worktree are useful for implementation
validation only. Tables and public claims must be regenerated from a clean,
merged commit and must retain the manifest digest, dependency-lock digest, and
git provenance embedded by the experiment artifact contract.
