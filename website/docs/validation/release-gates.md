---
title: Release Gates
description: Choose the right validation depth for local development, release candidates, and public claims.
---

# Release Gates

Release gates keep development fast while protecting public quality claims.

## Fast Loop

Run while editing core retrieval, graphify, or plan code:

```bash
make quick
```

## Release Candidate

Run before publishing a new package:

```bash
make release-check
```

## Public Benchmark Claim

Run the full benchmark configuration only when updating README or documentation
claims. Store the dataset, model, configuration, and result artifact.

## Related Pages

- [Benchmarks](./benchmarks.md)
- [BFCL-Style Evaluation](./bfcl-style-evaluation.md)
