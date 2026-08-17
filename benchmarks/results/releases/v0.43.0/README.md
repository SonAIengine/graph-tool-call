# v0.43.0 release evidence

This directory contains the deterministic release artifacts for
graph-tool-call 0.43.0.

- `dependency-chain-evidence.json` records the target and
  prerequisite-producer regression used by the README.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.
- `../../arazzo_long_horizon_0.43.json` records paired OpenAPI-only and
  OpenAPI-plus-Arazzo evaluation for 3-, 10-, and 30-call workflows in
  1,000-tool catalogs.
- `../../arazzo_long_horizon_deepseek_v4_flash_20260816.json` records a
  model-in-the-loop run over the same workflow lengths. All nine committed
  cases passed target, plan, execution-order, binding, and goal-completion
  gates.

Regenerate and validate the deterministic release artifacts with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
make arazzo-long-horizon-benchmark \
  OUT=benchmarks/results/arazzo_long_horizon_0.43.json
```

The dependency and observability artifacts do not use an LLM. Observability
latency is a local Python microbenchmark rather than an exporter or service
SLO. The DeepSeek result is a nine-case regression run, not a population-level
accuracy estimate or external leaderboard score.
