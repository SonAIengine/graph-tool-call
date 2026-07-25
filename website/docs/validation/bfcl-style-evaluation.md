---
title: BFCL-Style Evaluation
description: Document how graph-tool-call can be evaluated with tool-call benchmark methodology.
---

# BFCL-Style Evaluation

BFCL-style evaluation should be used when making public claims about tool-call
quality. It is heavier than the fast development loop and should run near
release candidates or benchmark claim updates.

This page is about methodology, not a permanent leaderboard claim. Results are
only meaningful when the dataset, model, retrieval mode, Top-K policy, and run
artifact are stated together.

## Evaluation Layers

| Layer | Purpose | Run Frequency |
| --- | --- | --- |
| deterministic retrieval | check whether expected tools are surfaced | every search change |
| model-in-the-loop target selection | check whether an LLM chooses correctly from the reduced catalog | release candidate |
| argument readiness | check whether selected calls have enough argument evidence | release candidate |
| execution-safe subset | check real API or fixture execution only when safe | gated/manual |

Do not use a full BFCL-style run as the normal inner loop. Use smaller
deterministic fixtures while developing.

## What To Measure

- target selection correctness
- plan validity
- argument readiness
- execution outcome when safe
- failure classification
- latency and token context budget

## Required Run Metadata

Every saved result should include:

- date
- graph-tool-call version or commit
- dataset and case count
- model/provider when a model is involved
- retrieval mode and Top-K
- prompt or native tool-call mode
- whether arguments were judged by exact match, semantic match, or evaluator
- output artifact path
- known limitations

## Example Workflow

```bash
make quick

poetry run python -m benchmarks.bfcl_tool_selection.run \
  --limit 25 \
  --top-k 5 \
  --json > /tmp/gtc-bfcl-smoke.json
```

Use a smoke run to catch regressions. Use a larger, repeated, model-in-the-loop
run only when updating public documentation or release notes.

## What To Avoid

Do not publish benchmark numbers from narrow smoke tests. A public claim should
link to the dataset, model, run configuration, and stored result artifact.

Avoid:

- mixing deterministic retrieval scores with LLM tool-call scores
- comparing against another benchmark without matching dataset and evaluator
- hiding failed cases
- reporting a single lucky run without repeats or confidence notes
- turning dev-host execution results into general model quality claims

## Reporting Template

```text
Dataset:
Model:
graph-tool-call version:
Retrieval mode:
Top-K:
Case count:
Metric:
Result:
Artifact:
Limitations:
```

## Related Pages

- [Benchmarks](./benchmarks.md)
- [Release Gates](./release-gates.md)
- [XGEN Scale Gates](./xgen-scale-gates.md)
