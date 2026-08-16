# v0.42.0 release evidence

This directory contains the model-free release artifacts for graph-tool-call
0.42.0.

- `dependency-chain-evidence.json` records the deterministic target and
  prerequisite-producer regression used by the README.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.
- `../../arazzo_long_horizon_0.42.json` records paired OpenAPI-only and
  OpenAPI-plus-Arazzo evaluation for 3-, 10-, and 30-call workflows in
  1,000-tool catalogs.

Regenerate and validate the release artifacts with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
make arazzo-long-horizon-benchmark \
  OUT=benchmarks/results/arazzo_long_horizon_0.42.json
```

These deterministic benchmarks do not use an LLM. The observability latency
value is a local Python microbenchmark and does not measure exporter backend or
service network latency. The Arazzo result measures engine workflow evidence,
planning, binding, and execution-order behavior rather than model reasoning.
