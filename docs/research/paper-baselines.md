# Frozen Paper Retrieval Baselines

The unified paper harness implements twelve deterministic development
comparators:

| ID | Artifact key | Frozen behavior |
|---|---|---|
| B-1 | `seeded_random` | Per-case seeded sampling from sorted tool names |
| B0-O | `oracle` | Annotated targets, required producers, then alternatives |
| B1 | `bm25` | BM25 over tool name, one-line summary, and description |
| B2 | `dense` | Revision-pinned multilingual E5 cosine retrieval |
| B3 | `hybrid_rrf` | Unweighted RRF over complete B1 and B2 rankings |
| B4 | `flat_semantic_rrf` | B3 over frozen flat semantic metadata, without edges |
| B5 | `graph_untyped` | B4 plus non-contract graph adjacency with uniform edge weights |
| B6 | `graph_typed_contract` | B4 plus typed/confidence-weighted graph and IO-contract edges |
| B6a | `graph_consumer_aligned_contract` | B6 with opt-in required-consumer-aligned output promotion |
| B6b | `graph_consumer_aligned_admission` | B6a with one evidence-gated candidate-admission slot |
| B6c | `graph_budget_aware_schema_admission` | B6b ranking with contract projection for evidence-admitted candidates |
| B7 | `full_graph_pipeline` | B6 plus deterministic target selection and bounded producer expansion |

These baselines are research comparators, not product retrieval modes. They
deliberately avoid contract scoring, target selection, and graph evidence.
B4 observes normalized semantic labels but does not perform query expansion or
graph traversal.

## Run

```bash
poetry install --with dev -E embedding-local
make paper-baseline-run
make paper-graph-ablation
make paper-producer-coverage
make paper-output-promotion
make paper-candidate-admission
make paper-contract-projection

TOP_K=8 SEED=17 OUT=/tmp/paper-baselines-k8.json \
  make paper-baseline-run

TOKEN_BUDGET=4096 OUT=/tmp/paper-baselines-4k.json \
  make paper-baseline-run

BOOTSTRAP_RESAMPLES=1000 OUT=/tmp/paper-graph-ablation.json \
  make paper-graph-ablation

BOOTSTRAP_RESAMPLES=1000 OUT=/tmp/paper-producer-coverage.json \
  make paper-producer-coverage

BOOTSTRAP_RESAMPLES=1000 OUT=/tmp/paper-output-promotion.json \
  make paper-output-promotion

BOOTSTRAP_RESAMPLES=1000 OUT=/tmp/paper-candidate-admission.json \
  make paper-candidate-admission

BOOTSTRAP_RESAMPLES=1000 OUT=/tmp/paper-contract-projection.json \
  make paper-contract-projection
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

### B5 Frozen Untyped Graph

B5 starts from the complete B4 ranking. Its top five B4 candidates are the
only graph seeds, so B4-to-B5 does not change the lexical, dense, semantic, or
fusion channels. The graph is built without contract promotion. Contract-only
edges are also rejected defensively at traversal time.

Every remaining edge is treated as untyped: relation, direction, confidence,
and evidence strength do not change its weight. Traversal is bidirectional,
bounded to depth two, and uses decay `1 / (0.5 * depth + 1)`. The strongest
path score ranks an expanded tool; it is not added to that tool's B4 score.
Seeds retain their normalized B4 score, preventing lexical/semantic and graph
channels from counting the same candidate twice. Tools that are neither seeds
nor graph-reached retain only their B4 tie-break order. This policy is
identified as `paper-graph-rerank-v1`.

### B6 Frozen Typed Contract Graph

B6 uses the same complete B4 ranking, five seeds, depth, decay, and
seed-versus-path score policy as B5. Its graph additionally promotes generic
`api_contract.consumes` and `api_contract.produces` rows into data-flow edges.
Relation and confidence weights are the frozen graph-tool-call defaults
recorded in the benchmark module. No target selector, producer expansion,
learning suggestion, manual edge, or run-observed trace is applied.

The B5-to-B6 paired delta therefore measures adding typed relation/confidence
evidence and deterministic IO-contract edges together. It does not claim to
separate those two subcomponents; a finer contract-edge versus edge-weight
ablation belongs to the wider WP3 matrix.

### B6a Required-Consumer-Aligned Output Promotion

B6a is an opt-in cold-start ablation over B6. It promotes an otherwise
unpromoted response field only when a required data consumer in the same
collection supplies deterministic field or semantic evidence. It never reads
the benchmark query, expected target, required producer annotation, execution
trace, or LLM output.

The policy retains at most one shortest JSON path per newly promoted aligned
field by default, preserves every output already admitted by B6, keeps generic
response wrappers excluded, and restricts field-name-only matches to compatible
module or semantic scope. Evidence records the matching consumer, field, scope,
and policy revision. Edges from an alignment-only output are emitted only to
its evidenced consumers rather than every same-named field in the collection.

B6a uses the same complete B4 ranking, five protected seeds, graph traversal,
top-K surface, and token budget as B6. The B6-to-B6a delta therefore isolates
output promotion and its resulting contract edges. The policy remains off in
the product path until its graph-size and retrieval trade-offs are supported
on broader data.

### B6b Consumer-Aligned Candidate Admission

B6b keeps B6a's complete B4 ranking, five traversal seeds, graph, edge
weights, output-promotion policy, depth, and candidate/token budgets. It
changes only final top-K admission. At most one non-seed candidate can replace
the last protected seed.

A candidate qualifies without benchmark annotations only when:

1. a forward `api_contract` path ends at an output promoted by B6a for that
   exact required consumer;
2. the candidate's canonical action matches the first explicit action in the
   query; and
3. query resource terms overlap the candidate's normalized OpenAPI path
   module or primary resource.

The frozen policy revision is `paper-consumer-aligned-contract-slot-v1`.
Diagnostics record qualifying, admitted, and evicted candidates, plus path,
graph score, admission score, action evidence, and resource evidence.
Expected targets, required producers, traces, LLM output, product aliases, and
held-out cases are never ranking inputs.

### B6c Budget-Aware Contract Projection

B6c preserves B6b's complete ranking, candidate-admission decision, top-K,
token budget, graph, and evidence gates. It changes only the model-facing
selection schema for a candidate newly admitted by B6b. All other candidates
retain the complete schema, and B6c never skips an oversized ranked candidate
to admit a later one. The B6b-to-B6c delta therefore isolates contract
projection rather than ranking or slot-allocation changes.

The frozen policy revision is `paper-contract-projected-admission-v1`. A
projected schema contains the tool name, a semantic description bounded to 240
characters, required parameters only, required-parameter descriptions bounded
to 160 characters, and at most 16 enum values per parameter. Optional
parameters and internal metadata are omitted. Existing one-line semantic
summaries are preferred over OpenAPI summaries and raw descriptions.

Projection eligibility comes only from B6b's collection-derived admission
evidence. Expected targets, required producers, held-out annotations, traces,
LLM output, and product aliases are not available to the policy. The protocol
requires the complete tool schema to be hydrated after target selection and
before argument generation or execution. The deterministic harness evaluates
selection-context availability; it does not claim that the projected form is
an execution contract.

### B7 Frozen Full Graph Pipeline

B7 takes B6's top-K surface, applies
`select_target_candidate(..., policy="strong_evidence")` without an LLM
target, and expands only the selected target. Producer expansion is limited to
one hop and three producers per required field. The selected target, admitted
producers, and remaining B6 candidates share the same top-K and token budget.

Learning suggestions, query-history signals, and product-specific aliases are
disabled. B6-to-B7 isolates the deterministic selector and producer-expansion
stage; B4-to-B7 reports the complete graph-tool-call contribution.

## Paired Ablations

Every artifact reports per-case deltas, improvement/regression/tie counts, and
bootstrap confidence intervals for:

| Artifact key | Comparison |
|---|---|
| `b5_minus_b4_topology` | untyped graph topology over the flat semantic baseline |
| `b6_minus_b5_typed_contract` | typed/confidence-weighted contract graph |
| `b6a_minus_b6_output_promotion` | required-consumer-aligned output promotion |
| `b6b_minus_b6a_candidate_admission` | one evidence-gated consumer-aligned candidate slot |
| `b6c_minus_b6b_contract_projection` | selection-time projection for the evidence-admitted candidate |
| `b7_minus_b6_selector_producers` | target selector and producer expansion |
| `b7_minus_b4_full_pipeline` | complete deterministic graph-tool-call pipeline |

Positive deltas mean higher quality for effectiveness metrics. For latency,
schema tokens, budget use, and truncation, the artifact's improvement counts
treat lower values as better. Graph construction remains a separately reported
setup cost rather than being charged to one query.

## Producer Edge Coverage Diagnostics

`paper-producer-coverage-v1` explains graph misses without changing any
ranking. It runs only in the offline evaluator and is explicitly marked
`ground_truth_only`; annotated targets and producers are never supplied to the
retriever or selector.

For every expected-target/required-producer pair, it records:

- whether both tools and their data `consumes`/`produces` contracts exist;
- field-name or semantic-tag matches, split into required and optional inputs;
- direct graph and `api_contract` edges, including compact edge evidence;
- shortest bidirectional retrieval paths and forward dependency paths, with
  graph and contract-only variants at B6's depth-two budget;
- whether target and producer were B6 seeds, and whether a seed can reach the
  producer; and
- stable reason codes for missing contracts, field mismatch, optional-only
  matches, unpromoted matching contracts, reversed edges, excessive depth,
  missing paths, and seed misses.

Pair reports live under
`cases[].diagnostics.producer_edge_coverage`. Aggregate and source-level
summaries live under `summary.producer_edge_coverage` and
`summary.producer_edge_coverage_by_source`. Empty single-tool cases do not
inflate rates.

## Train/Dev Implementation Pilot

The 2026-07-30 implementation-branch pilot used the pinned E5 encoder,
Qwen3 tokenizer, `K=5`, 29 train/dev cases, and 1,000 bootstrap resamples.
It did not open the held-out split.

| Baseline | Target Hit@5 | Producer Recall@5 | All required | MRR |
|---|---:|---:|---:|---:|
| B2 dense | 0.9655 | 0.6667 | 0.8966 | 0.9207 |
| B4 flat semantic | 0.9310 | 0.6667 | 0.8621 | 0.8305 |
| B5 untyped graph | 0.9310 | 0.6667 | 0.8621 | 0.8305 |
| B6 typed contract | 0.9310 | 0.6667 | 0.8621 | 0.8305 |
| B6a aligned output | 0.9310 | 0.6667 | 0.8621 | 0.8305 |
| B6b candidate admission | 0.9310 | 0.8333 | 0.8966 | 0.8305 |
| B6c contract projection | 0.9310 | 0.8333 | 0.8966 | 0.8305 |
| B7 full deterministic | 0.9310 | 0.6667 | 0.8621 | 0.7931 |

This pilot does not support H1 or H2. At `K=5`, the five protected B4 seeds
already fill the candidate budget, and available graph paths do not introduce
a stronger required producer. B7 preserves set-level recall but its
deterministic selector improves MRR on two cases and regresses five; the paired
B7-minus-B4 MRR delta is `-0.0374` with bootstrap 95% CI
`[-0.1322, 0.0603]`.

The same pinned run at `K=3` and `K=8` also produced zero B4-to-B5 and
B5-to-B6 effectiveness deltas. Dense producer recall rose from `0.5833` to
`1.0000` across that budget sweep, while the graph profiles matched B4 at each
K. This points to missing useful producer paths or insufficient admissible
edge evidence, rather than a need for a larger graph score multiplier.

These are diagnostic development numbers from a dirty implementation
worktree, not publication evidence. The immediate implication is to run the
remaining token-budget sweeps and inspect missing producer-edge coverage and
ambiguous selector evidence. It is not a reason to tune on or open the
held-out family.

### Producer coverage follow-up

The pinned `K=5` replay was repeated after adding diagnostics. Its seven
annotated producer-target pairs produced:

| Diagnostic | Count | Rate |
|---|---:|---:|
| consumer input contract present | 7/7 | 1.0000 |
| producer output contract present | 4/7 | 0.5714 |
| producer output promoted for graph construction | 1/7 | 0.1429 |
| any contract field match | 4/7 | 0.5714 |
| required-input contract match | 2/7 | 0.2857 |
| promoted contract field match | 0/7 | 0.0000 |
| direct contract edge | 0/7 | 0.0000 |
| depth-two contract-only path | 0/7 | 0.0000 |
| direct graph edge of any evidence class | 1/7 | 0.1429 |
| depth-two bidirectional retrieval path | 4/7 | 0.5714 |
| depth-two forward dependency path | 1/7 | 0.1429 |
| producer already in the five B4 seeds | 5/7 | 0.7143 |
| producer reachable from a seed | 6/7 | 0.8571 |

The pair statuses are one direct structural edge, three bounded structural
paths, and three uncovered pairs. All three non-direct bounded paths require
traversing at least one edge in reverse. Three pairs have no producer output
contract, three more have raw outputs that are not promoted for graph
construction, four have raw matches that disappear from the promoted surface,
two have only optional consumer matches, and one has a reversed direct edge.

This explains the zero B5-to-B6 gain more precisely: the frozen B6 graph has
no promoted field match or contract path for any annotated producer, while
five producers are already flat-retrieval seeds. Increasing a graph multiplier
cannot repair either condition.

### Output-promotion follow-up

The pinned train/dev replay then compared B6 with B6a using the same E5 and
Qwen3 revisions, `K=5`, seed 17, 29 cases, and 1,000 bootstrap resamples. The
held-out split remained unopened. The artifact ID is
`exp-7b44cb52c35e81324819023d`.

| Producer diagnostic | B6 | B6a |
|---|---:|---:|
| promoted producer output | 1/7 | 4/7 |
| promoted contract field match | 0/7 | 2/7 |
| promoted required-field match | 0/7 | 2/7 |
| direct contract edge | 0/7 | 2/7 |
| bounded forward contract path | 0/7 | 2/7 |
| direct graph edge | 1/7 | 3/7 |
| bounded forward graph path | 1/7 | 4/7 |
| matching fields not promoted | 4/7 | 2/7 |

The structural hypothesis was supported for two annotated pairs, but the
retrieval hypothesis was not: B6 and B6a both produced target Hit@5 `0.9310`,
producer Recall@5 `0.6667`, all-required-found `0.8621`, and MRR `0.8305`.
All 29 effectiveness comparisons were ties.

The reason is part of the result. B6 and B6a protect all five B4 seeds at
`K=5`; newly reachable producers cannot displace a seed even when a valid
contract path now exists. The experiment therefore identifies candidate
admission and seed-slot allocation as the next isolated ablation, rather than
justifying another edge-weight change.

Output promotion also has a measurable graph cost. On the public Kubernetes
source, final edges increased from `616` to `991`, promoted produces from
`814` to `1,761`, and `5,442` extra JSON paths were rejected by the per-field
cap. On Petstore, edges increased from `30` to `41`. These development results
keep B6a opt-in and motivate a later precision/graph-growth study before any
default rollout. Optional-consumer evidence and producer-cap changes remain
separate experiments.

### Candidate-admission follow-up

The clean B6b replay used commit `ac3e7c0`, the same pinned E5 and Qwen3
revisions, `K=5`, a 2,048-token budget, seed 17, 29 train/dev cases, and 1,000
bootstrap resamples. The held-out split remained unopened. Artifact
`exp-15f214a1d4b96cea07bdf098` (run
`run-fa09c248ed37ccaa84c7`) passed schema validation with `git_dirty=false`.

| Candidate-count metric | B6a | B6b |
|---|---:|---:|
| target Hit@5 | 0.9310 | 0.9310 |
| producer Recall@5 | 0.6667 | 0.8333 |
| required-tool Recall@5 | 0.9138 | 0.9310 |
| all-required-found | 0.8621 | 0.8966 |
| Precision@5 | 0.2293 | 0.2362 |
| MRR | 0.8305 | 0.8305 |

Exactly one effectiveness case improved and none regressed. For the
Kubernetes pod-log workflow, B6b admitted `listCoreV1NamespacedPod` through
the direct `readCoreV1NamespacedPodLog -> listCoreV1NamespacedPod`
aligned-contract path and evicted the fifth protected seed. No other case
passed all evidence gates.

The 2,048-token view did not retain that gain: producer recall stayed at
`0.5000` and all-required-found at `0.7931` for both methods. The admitted
producer's complete schema did not fit as the fifth item under
`ranked-greedy-whole-schema-v1`, so B6b selected four schemas and stopped.
Mean serialized schema use fell from `494.86` to `466.62` tokens, while the
truncation rate rose from `0.1724` to `0.2069`. This is a negative
context-budget result, not evidence that the producer is available to the
model. Budget-aware admission or schema projection must therefore be tested
as a separate ablation before B6b can support an end-to-end context claim.

### Contract-projection follow-up

The clean B6c replay used commit
`9f27de8f4b0ad92ae922543aabd83b6ab2e079c6`, the same pinned E5 and Qwen3
revisions, `K=5`, a 2,048-token budget, seed 17, 29 train/dev cases, and 1,000
bootstrap resamples. The held-out split remained unopened. Artifact
`exp-c7f4b09c92ca16f14fafde76` (run
`run-d69ba667aa2fb4705ce7`) passed schema validation with `git_dirty=false`.

| Token-budget metric | B6b | B6c |
|---|---:|---:|
| target Hit@5 | 0.8966 | 0.8966 |
| producer Recall@5 | 0.5000 | 0.6667 |
| required-tool Recall@5 | 0.8621 | 0.8793 |
| all-required-found | 0.7931 | 0.8276 |
| Precision@5 | 0.2828 | 0.2879 |
| MRR | 0.8218 | 0.8218 |
| mean admitted schemas | 4.2069 | 4.2414 |
| mean schema tokens | 466.62 | 468.62 |
| truncation rate | 0.2069 | 0.1724 |

Exactly one effectiveness case improved and none regressed. In
`kubernetes-dev-pod-logs-en`, B6c retained the B6b ranking and admitted
projected `listCoreV1NamespacedPod` as the fifth schema. Projection saved
1,321 tokens relative to that tool's complete selection schema, leaving a
1,211-token catalog. Producer recall for the case increased from `0` to `1`
and required-tool recall from `0.5` to `1.0`.

The two-token increase in mean schema use is intentional: B6c used previously
unavailable budget to expose one relevant fifth tool. The paired bootstrap 95%
intervals still include zero: producer-recall delta `[0.0000, 0.5000]`,
required-tool-recall delta `[0.0000, 0.0517]`, and all-required delta
`[0.0000, 0.1034]`. This small development result supports the packing
mechanism and absence of observed regressions; it is not a broad statistical
claim. The subsequent clean Qwen3.6-27B model loop confirmed that the same case
improves after target/support selection and complete-schema hydration:
producer recall and end-to-end structural validity each rose by `0.0345` over
29 unique cases with no observed regression. The publication-candidate replay
repeated all 29 cases three times and reproduced the same aggregate deltas in
every repeat. Its original-case-clustered 95% intervals are
`[0.0000, 0.1034]` for producer recall and end-to-end validity and
`[0.0000, 0.0517]` for required-tool recall. They still include zero and the
held-out split remains sealed, so this is stable mechanism evidence rather
than a broad statistical claim. See
[`paper-model-loop.md`](paper-model-loop.md) for the frozen protocol, exact
artifact IDs, token cost, and interpretation boundary.

## Metrics And Budget

Every query records two paired views of the same frozen ranking:

1. the original candidate-count view, capped at `K`;
2. a token-budget view, capped at both `K` and 2,048 model-facing tokens by
   default.

Both views record target Hit@K, producer Recall@K, required-tool Recall@K,
all-required-found, Precision@K, MRR, AP, graded nDCG@K, latency, candidate
count, normalized model-facing schema characters, and UTF-8 bytes. The
token-budget view additionally records schema tokens, budget utilization,
truncation status, token-accounting latency, per-tool schema mode, projected
schema count, and tokens saved by projection. The default model-facing payload
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
B6c alone replaces an evidence-admitted candidate's complete schema with the
bounded contract projection declared above and records both the schema mode
and token savings. It otherwise follows the same ranked-prefix policy.

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
