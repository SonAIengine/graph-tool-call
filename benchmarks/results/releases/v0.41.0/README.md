# v0.41.0 release evidence

This directory contains the model-free release artifacts for graph-tool-call
0.41.0.

- `dependency-chain-evidence.json` records the deterministic target and
  prerequisite-producer regression used by the README.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.
- Arazzo workflow ordering, runtime binding promotion, artifact persistence, and
  source provenance are covered by the public workflow evidence tests.

Regenerate and validate the artifacts with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
```

The deterministic release benchmark does not use an LLM. The observability
latency value is a local Python microbenchmark and does not measure exporter
backend or service network latency.
