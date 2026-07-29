# Frozen Paper Retrieval Baselines

The unified paper harness implements six deterministic development
comparators:

| ID | Artifact key | Frozen behavior |
|---|---|---|
| B-1 | `seeded_random` | Per-case seeded sampling from sorted tool names |
| B0-O | `oracle` | Annotated targets, required producers, then alternatives |
| B1 | `bm25` | BM25 over tool name, one-line summary, and description |
| B2 | `dense` | Revision-pinned multilingual E5 cosine retrieval |
| B3 | `hybrid_rrf` | Unweighted RRF over complete B1 and B2 rankings |
| B4 | `flat_semantic_rrf` | B3 over frozen flat semantic metadata, without edges |

These baselines are research comparators, not product retrieval modes. They
deliberately avoid contract scoring, target selection, and graph evidence.
B4 observes normalized semantic labels but does not perform query expansion or
graph traversal.

## Run

```bash
poetry install --with dev -E embedding-local
make paper-baseline-run

TOP_K=8 SEED=17 OUT=/tmp/paper-baselines-k8.json \
  make paper-baseline-run

TOKEN_BUDGET=4096 OUT=/tmp/paper-baselines-4k.json \
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

### B2 Fixed Dense

B2 uses
[`intfloat/multilingual-e5-small`](https://huggingface.co/intfloat/multilingual-e5-small/tree/fd1525a9fd15316a2d503bf26ab031a61d056e98)
at commit `fd1525a9fd15316a2d503bf26ab031a61d056e98` (MIT license).
The model supports the English and Korean development queries without changing
models between slices. It embeds exactly the same three text fields as B1,
using the E5 `query: ` and `passage: ` prefixes and normalized embeddings.
Ranking uses cosine similarity with a stable tool-name tie break.

The reference command runs on CPU with batch size 32. The artifact records the
model commit, sentence-transformers version, device, batch size, model load
latency, and document encoding latency for each source. Per-case dense latency
covers query encoding and ranking; it excludes both separately reported setup
stages.

### B3 Fixed Hybrid

B3 computes unweighted reciprocal rank fusion over the complete B1 and B2
rankings:

```text
RRF(tool) = 1 / (60 + rank_bm25) + 1 / (60 + rank_dense)
```

It uses `k=60`, no tuned channel weights, and no graph, contract, selector, or
semantic boosts. B3 latency is the sum of B1 ranking, B2 query ranking, and RRF
fusion for the case.

### B4 Fixed Flat Semantic Hybrid

B4 repeats B3 with four normalized metadata values appended to the B1/B2
document:

```text
metadata.ai_metadata.canonical_action
metadata.ai_metadata.primary_resource
metadata.openapi.path_module
metadata.ai_metadata.result_shape
```

Each non-empty value is serialized with its field name. Values equal to
`unknown` or `unassigned` are omitted. Existing normalized metadata wins. For
OpenAPI tools only, missing values are filled by the public deterministic
`derive_openapi_tool_semantics()` helper. The harness does not invent missing
GraphQL or MCP semantic labels; per-source field coverage is recorded in the
artifact so this limitation remains visible.

B4 uses independent BM25 and E5 indexes over the augmented document and fuses
their complete rankings with the same unweighted RRF formula and `k=60` as B3.
It does not use parameters, IO-contract fields, graph edges, query aliases,
semantic query expansion, target selection, producer expansion, manual
evidence, or run-observed evidence. It is therefore the strongest candidate
flat-metadata comparator, not a graph-tool-call pipeline result.

Per-case B4 latency covers semantic BM25 ranking, semantic E5 query encoding
and ranking, and RRF fusion. One-time semantic-document construction, BM25
index construction, and dense document encoding are reported separately by
source under the artifact setup block.

## Metrics And Budget

Every query records two paired views of the same frozen ranking:

1. the original candidate-count view, capped at `K`;
2. a token-budget view, capped at both `K` and 2,048 model-facing tokens by
   default.

Both views record target Hit@K, producer Recall@K, required-tool Recall@K,
all-required-found, Precision@K, MRR, AP, graded nDCG@K, latency, candidate
count, normalized model-facing schema characters, and UTF-8 bytes. The
token-budget view additionally records schema tokens, budget utilization,
truncation status, and token-accounting latency. The model-facing payload
includes name, description, and parameters but excludes internal metadata.
Relevance grades are:

- expected target: `3`;
- required producer: `2`;
- acceptable alternative: `1`.

Aggregate producer recall is computed only over cases that annotate required
producers. Bootstrap 95% confidence intervals use 1,000 deterministic
resamples for both views.

Token accounting uses
[`Qwen/Qwen3-4B`](https://huggingface.co/Qwen/Qwen3-4B/tree/1cfa9a7208912126459214e8b04321603b3df60c)
at commit `1cfa9a7208912126459214e8b04321603b3df60c` with
`add_special_tokens=false`. Complete schemas are serialized as one canonical,
compact JSON array with sorted object keys. The policy
`ranked-greedy-whole-schema-v1` accepts the longest ranked prefix that fits the
budget. It stops at the first schema that would exceed the limit, never skips
that schema to admit a later one, and never truncates a schema internally.

Only the tool catalog payload is counted. Query and system-prompt tokens are
excluded because they are identical across paired retrieval methods. This
supports fair candidate-context comparisons; it is not a claim about complete
end-to-end prompt tokens. The candidate-count fields remain in the artifact for
backward comparison, while publication context-efficiency comparisons use the
parallel `token_budget_*` fields.

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
