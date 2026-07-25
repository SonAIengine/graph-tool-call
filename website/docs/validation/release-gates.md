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

The goal is not to run every expensive check all the time. The goal is to match
the check to the claim being made.

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

Before publishing, record the exact version, git commit, and release artifact
location. If the docs mention a feature as released, the package version should
already expose the referenced public import or CLI command.

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

Use this distinction when choosing how much to run:

| Claim Type | Minimum Evidence |
| --- | --- |
| deterministic retrieval improvement | fixture id, command, before/after metrics, result artifact |
| LLM target-selection behavior | model/provider, prompt/config, seed or run id, raw result artifact |
| execute success rate | auth readiness state, host allowlist, mutation safety, cleanup result |
| public benchmark number | dataset version, package version, model/provider, timestamp, reproducible script |
| UI/docs behavior | built static site, locale route check, screenshot or preview URL |

## Documentation Gate

For the official docs site:

```bash
cd website
npm run typecheck
npm run build
```

Also verify both locale routes and search indexes when changing navigation,
i18n, or search configuration.

For docs that claim a public API, CLI flag, event field, or result schema, check
the implementation or tests that define that contract. A docs page should not be
the source of truth for an API that the package does not expose.

Recommended evidence for docs PRs:

- `npm run typecheck`
- `npm run build`
- search index contains new important terms in English and Korean
- desktop and mobile screenshots for homepage/layout changes
- referenced test files, commands, and public imports exist

## PR And Pages Gate

Before merging docs or release changes:

1. Push the branch and wait for GitHub CI.
2. Confirm Documentation build is green.
3. Confirm library CI is green when code-adjacent docs mention tests or public APIs.
4. Confirm the PR merge state is clean.
5. After merge, wait for GitHub Pages deployment before sharing the public URL.

GitHub Actions warnings about runner Node versions are not release blockers by
themselves, but failed build/test jobs are.

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
