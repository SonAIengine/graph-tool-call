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

The native B-1/B0-O/B1 runner writes this schema directly rather than passing
through a legacy adapter:

```bash
make paper-baseline-run
```

Its exact baseline and held-out access contracts are documented in
[`paper-baselines.md`](paper-baselines.md).

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
