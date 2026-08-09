# v0.38.0 release evidence

This directory contains two complementary, model-free release artifacts.

- `dependency-chain-evidence.json` records the deterministic target and
  prerequisite-producer regression used by the README.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.

Regenerate and validate them with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
```

The observability latency value is a local Python microbenchmark. The check
runs a fresh measurement and enforces the documented `5ms/span` p95 ceiling;
it does not measure exporter backend or service network latency.
