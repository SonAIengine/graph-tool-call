# v0.46.0 release evidence

This directory contains deterministic release artifacts for graph-tool-call
0.46.0.

- `dependency-chain-evidence.json` records target and prerequisite-producer
  retrieval, plan coverage, and binding support for the public commerce
  regression.
- `observability-evidence.json` records result invariance, deterministic replay,
  secret scrubbing, reason coverage, serialized trace size, and measured trace
  capture overhead.

Regenerate and validate the artifacts with:

```bash
make launch-evidence
make launch-evidence-check
make observability-evidence
make observability-evidence-check
```

These artifacts do not use an LLM. The seven-case dependency regression is not
a population-level accuracy estimate, and the observability latency is a local
Python microbenchmark rather than an exporter or service SLO.
