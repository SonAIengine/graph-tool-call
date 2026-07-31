# Unified Experiment Artifact

The paper evaluation uses one versioned artifact contract for deterministic
retrieval, model, execution, and XGEN validation runs. Existing benchmark
serializers remain supported; adapters normalize their common evidence without
rewriting historical result files.

## Why This Exists

Historical benchmark outputs use several shapes. That makes it too easy to
compare runs with different code, data, seeds, tokenizer revisions, or model
revisions. Schema v1 records those differences explicitly.

Every artifact contains:

- deterministic `run_id` for the frozen configuration;
- content-addressed `artifact_id` for the exact result;
- git commit, package version, Python version, and dependency lock digest;
- dataset ID, split, and source digest;
- seed, model, tokenizer, and replay command;
- normalized expected/observed values, metrics, stage evidence, and failures;
- summary statistics and the digest of the original legacy report.

No environment variables, credentials, request bodies, or raw model reasoning
belong in an experiment artifact.

## Create From An Existing Result

```bash
poetry run python -m benchmarks.experiment.cli create \
  benchmarks/results/baseline_retrieval.json \
  --source-type reporter \
  --dataset-id legacy-public-retrieval \
  --split dev \
  --seed 0 \
  --tokenizer-name cl100k_base \
  --tokenizer-revision tiktoken-pinned-revision \
  --out /tmp/baseline.experiment.json \
  --replay-command python -m benchmarks.run_benchmark
```

Model runs must additionally pin `--model-name`, `--model-provider`, and
`--model-revision`.

## Validate And Inspect

```bash
poetry run python -m benchmarks.experiment.cli validate \
  /tmp/baseline.experiment.json

poetry run python -m benchmarks.experiment.cli inspect \
  /tmp/baseline.experiment.json

poetry run python -m benchmarks.experiment.cli replay \
  /tmp/baseline.experiment.json
```

`replay` only prints the frozen command. It never executes commands embedded in
an artifact.

Run the contract suite with:

```bash
make paper-harness-check
```

The native B-1/B0-O/B1/B2/B3/B4/B5/B6/B6a/B6b/B6c/B7 runner writes this
schema directly rather than passing through a legacy adapter:

```bash
make paper-baseline-run
```

Its exact baseline and held-out access contracts are documented in
[`paper-baselines.md`](paper-baselines.md).

The deterministic E0 adapter-conformance runner also writes schema v1
directly:

```bash
make paper-adapter-conformance
```

It records source-fact policy revisions, per-source micro/macro contract
fidelity, exact serialization hashes, and structured negative probes. See
[`adapter-conformance.md`](adapter-conformance.md).

The native runner records the embedding model under `model` and the
model-facing context tokenizer under `tokenizer`; these are deliberately
separate roles. Candidate-count results remain under `observed`, `metrics`,
`summary.baselines`, and `statistics.bootstrap`. The paired token-budget view
is additive:

- per case: `token_budget_observed` and `token_budget_metrics`;
- aggregate: `summary.token_budget_baselines` and
  `summary.token_budget_per_source`;
- confidence intervals: `statistics.token_budget_bootstrap`;
- frozen policy: `config.token_budget`.

Budget-aware schema projection is additive to the same per-case view:

- policy identity: `token_budget_observed.<baseline>.policy_revision`;
- selected representation: `schema_modes` (`full` or `contract_projected`);
- projection use: `projected_schema_count`;
- savings against complete schemas: `projection_saved_tokens`;
- exact payload size: `schema_chars` and `schema_utf8_bytes`.

The paired B6b/B6c model loop also writes schema v1 directly:

```bash
make paper-model-loop \
  BASELINE_ARTIFACT=/tmp/graph-tool-call-paper-contract-projection.json \
  MODEL=model-name \
  MODEL_REVISION=immutable-revision
```

Its model cases use composite IDs
`<original-case>::repeat-<n>::<baseline>`. The frozen pair key, baseline,
repeat, and paired seed live under `cases[].context`. Selection catalog hashes,
schema modes, model decisions, complete-schema hydration hashes, plan
validation, stage tokens/latency, and structured failure reasons are recorded
under `observed`, `metrics`, `stages`, and `failure`. Aggregate paired deltas
live under `summary.paired_b6c_minus_b6b`, with confidence intervals under
`statistics.paired_bootstrap`.

Repeated model runs additionally record `summary.repeat_analysis`, including
per-repeat paired summaries, delta ranges, delta standard deviations, and the
fraction of repeat-evaluable original cases whose paired outcome is identical
across repeats.
Publication inference uses `statistics.clustered_paired_bootstrap`, which
clusters by `original_case_id` and averages repeat deltas within each original
case before resampling. The legacy repeated-row interval remains under
`statistics.paired_bootstrap` for backward compatibility but does not increase
the independent task count.

An existing artifact can be reanalyzed without model calls:

```bash
ARTIFACT=/tmp/graph-tool-call-paper-b6c-model-loop.json \
make paper-model-loop-analysis
```

The deterministic analysis report references the source artifact ID, run ID,
and SHA-256 and records `model_calls_performed=0`.

The model artifact references the exact deterministic input through
`dataset.baseline_artifact_id`, `dataset.baseline_run_id`, and
`source.sha256`. Ground-truth labels remain evaluation-only. See
[`paper-model-loop.md`](paper-model-loop.md) for the two-pass protocol.

The budgeted LLM catalog-selector comparison also writes schema v1 directly:

```bash
BASELINE_ARTIFACT=/tmp/graph-tool-call-paper-contract-projection.json \
MODEL=model-name \
MODEL_REVISION=immutable-revision \
make paper-llm-catalog-baseline
```

It records paired B6c/B0-L rows, complete first-round catalog coverage,
per-round chunk hashes, maximum per-call catalog tokens, cumulative catalog
tokens scanned, selector calls, provider tokens, and latency. B0-L never uses
graph edges, retrieval ranks, or evaluation labels. See
[`paper-llm-catalog-baseline.md`](paper-llm-catalog-baseline.md).

Graph ablations are paired on the same cases:

- aggregate deltas: `summary.ablations` and
  `summary.token_budget_ablations`;
- source slices: `summary.per_source_ablations`;
- paired confidence intervals: `statistics.paired_bootstrap` and
  `statistics.token_budget_paired_bootstrap`;
- graph build cost and edge profile: `summary.setup.graph_profiles_by_source`;
- per-case graph/selector evidence: `cases[].observed.<baseline>.diagnostics`.

Ground-truth-only producer coverage diagnostics are additive and never affect
retrieval:

- frozen policy: `config.producer_edge_diagnostics`;
- per annotated pair: `cases[].diagnostics.producer_edge_coverage.pairs`;
- consumer-aligned comparison:
  `cases[].diagnostics.producer_edge_coverage_consumer_aligned.pairs`;
- aggregate contract/edge/path/seed rates:
  `summary.producer_edge_coverage`;
- consumer-aligned aggregate:
  `summary.producer_edge_coverage_consumer_aligned`;
- source slices: `summary.producer_edge_coverage_by_source`.

The diagnostic config must retain `used_for_ranking=false` and
`evaluation_scope=ground_truth_only`. An artifact that uses expected targets
or producers as ranking input is not comparable to the declared B1-B7, B6a,
B6b, and B6c baselines. B6a derives promotion evidence only from collection
contracts. B6b derives admission evidence only from those promoted contracts,
the query, and collection semantics. B6c projects only candidates identified
by that B6b admission evidence and does not change ranking. Ground-truth
diagnostics are computed after ranking.

The tokenizer name, immutable revision, library version, serialization
revision, special-token policy, and replay flags all participate in `run_id`.

## Identity Rules

`run_id` hashes the benchmark identity, methodology, run kind, seed, dataset,
configuration, model, tokenizer, replay command, and core software provenance.
Changing result metrics does not change `run_id`.

`artifact_id` hashes the complete artifact except for `artifact_id` itself.
Changing a result, timestamp, failure, or evidence changes the artifact ID.

This distinction supports repeated runs of one frozen protocol while making
every saved result tamper-evident.

## Legacy Adapters

Schema v1 accepts these source types:

- `reporter`
- `pipeline`
- `bfcl_tool_selection`
- `bfcl_model`
- `xgen_tool_graph`
- `xgen_api_scale`
- `execution`

The adapter stores the original report digest and preserves its existing
serializer. It does not silently infer a trustworthy model revision or
tokenizer revision; those values must be supplied for publication-grade runs.
