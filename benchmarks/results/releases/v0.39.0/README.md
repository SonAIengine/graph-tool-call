# v0.39.0 release evidence

This directory contains the model-free release artifacts for graph-tool-call
0.39.0.

- `dependency-chain-evidence.json` records the deterministic target and
  prerequisite-producer regression used by the README.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.
- The execution-flow contract added in 0.39.0 is covered by the public contract,
  direction, ambiguity, runner-status, trace-learning, and secret-safety tests.

Regenerate and validate the artifacts with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
```

The observability latency value is a local Python microbenchmark. The check
runs a fresh measurement and enforces the documented `5ms/span` p95 ceiling;
it does not measure exporter backend or service network latency.
