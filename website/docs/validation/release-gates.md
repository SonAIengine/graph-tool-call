---
title: Release Gates
description: Choose validation depth for local development, release candidates, and public claims.
---

# Release Gates

Release gates keep development fast while protecting package quality and public
claims. The rule is simple: run the cheapest check that can catch the class of
bug you are likely to have introduced, then widen the gate before release.

## Gate Levels

| Level | When To Use | Commands |
| --- | --- | --- |
| Fast loop | Editing graphify/search/plan code | `make quick` |
| Focused test | Editing one feature area | `poetry run pytest tests/test_*.py -q` |
| Website | Editing docs site | `cd website && npm run typecheck && npm run build` |
| Full library | Before merge or release candidate | `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run pytest tests/ -q` |
| Release candidate | Before PyPI publishing | `make release-check` |
| Public claim | Before updating README/docs benchmark numbers | deterministic benchmark plus stored artifact, LLM run if claimed |

## Fast Loop

```bash
make quick
```

Use this during implementation. It should cover the public contracts most likely
to break in graphify, retrieval, selector, plan, and runner changes.

## Full Library Gate

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run pytest tests/ -q
```

Run this before asking for a review on non-trivial code changes.

## Release Candidate Gate

```bash
make release-check
```

Release candidates should also verify public imports and package build output.

```bash
make pypi-smoke
```

## Public Benchmark Gate

Run the full benchmark configuration only when updating public quality claims.
The result must include:

- dataset or fixture id
- graph-tool-call version
- model/provider when an LLM is used
- run configuration
- timestamp
- raw result artifact
- summary metrics

If a claim cannot be reproduced from committed fixtures or stored artifacts, do
not put it in public docs.

## Documentation Gate

For the official docs site:

```bash
cd website
npm run typecheck
npm run build
```

Also verify both locale routes and search indexes when changing navigation,
i18n, or search configuration.

## What Not To Do

- Do not run a five-hour LLM benchmark after every small edit.
- Do not publish PyPI from a red CI run.
- Do not update README numbers from local ad-hoc output.
- Do not treat successful search as proof that execute is ready.

## Related Pages

- [Benchmarks](./benchmarks.md)
- [Quality Lab](./quality-lab.md)
- [XGEN Scale Gates](./xgen-scale-gates.md)
- [BFCL-Style Evaluation](./bfcl-style-evaluation.md)
