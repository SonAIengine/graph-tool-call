# Public Heterogeneous Tool Corpus

This document defines the public corpus used by the graph-tool-call paper
protocol. The corpus is an auditable research artifact, not a folder of
convenient examples.

The canonical manifest is:

```text
benchmarks/corpus/manifest.json
```

Validate it with:

```bash
make paper-corpus-check
```

The command verifies local paths, SHA-256 digests, byte sizes, SPDX license
evidence, upstream revisions, API-family splits, ground-truth provenance,
adapter selection, tool counts, and annotated tool names.

## Current Status

The first seed is reproducible but intentionally not paper-ready:

```text
integrity=pass
paper_ready=fail
sources=3
families=3
queries=17
```

| Source | Type | Split | Tools | Queries | License |
|---|---|---:|---:|---:|---|
| Swagger Petstore `1.0.27` | OpenAPI | train | 19 | 6 | Apache-2.0 |
| project commerce schema | GraphQL introspection | dev | 4 | 5 | MIT |
| project filesystem fixture | MCP tools | test | 11 | 6 | MIT |

The remaining paper-readiness blocker is:

```text
paper_source_family_coverage_insufficient
```

Each source type currently has one API family. The protocol requires at least
two independently sourced families per source type before a held-out
generalization claim is allowed. Passing integrity does not authorize a paper
claim.

## Source Admission Contract

Every source row records:

| Field | Purpose |
|---|---|
| `id` | immutable snapshot identifier |
| `family_id` | leakage boundary shared by versions and aliases |
| `source_type` | canonical ingest source type |
| `adapter` | exact graph-tool-call adapter |
| `split` | `train`, `dev`, or `test` |
| `snapshot_path` | repository-local immutable artifact |
| `sha256`, `bytes` | tamper and accidental-refresh detection |
| `license` | SPDX ID and primary evidence URL |
| `provenance` | upstream URL, immutable revision, and derivation kind |
| `audit` | reviewer, review date, and completed license/revision/redistribution checks |
| `ground_truth_path` | paper schema v1 annotations |
| `ground_truth_sha256` | annotation snapshot integrity |
| `expected_tool_count` | adapter conformance expectation |
| `paper_core` | eligibility for primary paper metrics |
| `audit_status` | `audited`, `pending`, or `excluded` |

`paper_core=true` is accepted only with `audit_status=audited`, license
evidence, provenance, and ground truth. An unaudited source can be tracked for
future work but must not enter a primary result table.

## Ground-Truth Contract

Paper ground truth uses target and producer roles instead of the legacy flat
`expected_tools` list:

```json
{
  "case_id": "stable-family-split-case",
  "query": "Find an available pet and inspect its details.",
  "expected_targets": ["getPetById"],
  "required_producers": ["findPetsByStatus"],
  "acceptable_alternatives": [],
  "provenance": {
    "origin": "human-authored",
    "annotator_version": "seed-v1"
  }
}
```

This representation can later add execution assertions and equivalence groups
without changing the target/producer distinction.

## Split and Leakage Policy

The split unit is an API family, never an individual query.

- versions, snapshots, aliases, and paraphrases from one family stay together;
- a family cannot change source type across snapshots;
- train/dev tuning must not inspect test outcomes;
- query IDs are globally unique;
- test source hashes are frozen before release-candidate evaluation;
- synthetic and external sources are reported as separate slices.

The validator emits `family_split_leakage` if one family appears in multiple
splits.

## Integrity vs. Paper Readiness

The CLI has two independent gates:

```bash
# Must pass on every PR that changes the corpus.
poetry run python -m benchmarks.corpus.manifest --verify-ingest

# Deliberately fails until the complete public-corpus policy is satisfied.
poetry run python -m benchmarks.corpus.manifest \
  --verify-ingest \
  --require-paper-ready
```

`--no-verify-hashes` is available only for local schema inspection. It always
adds the `hash_verification_disabled` paper-readiness blocker and therefore
cannot establish a publishable result.

Integrity blockers include changed hashes, missing license evidence, path
escape, invalid annotation schema, absent tools, and family leakage.

Paper-readiness blockers include missing source types, missing splits,
insufficient independent families, and insufficient query coverage. This
separation allows incremental corpus work without representing a seed as a
finished benchmark.

## Adding a Source

1. Confirm redistribution rights from a primary license source.
2. Pin an immutable upstream revision or release tag.
3. Save a repository-local, credential-free snapshot.
4. Assign an API family before choosing a split.
5. Add independently authored target/producer annotations.
6. Record hashes and expected ingest tool count.
7. Run `make paper-corpus-check`.
8. Review whether the source is `paper_core`, `pending`, or `excluded`.

Never add:

- internal/customer API descriptions;
- credentials, cookies, tokens, user identifiers, or live auth headers;
- a public URL without redistribution permission;
- generated paraphrases in a different split from their seed;
- a modified test snapshot after final evaluation begins.

## Seed Provenance

- Swagger Petstore source and Apache-2.0 license:
  <https://github.com/swagger-api/swagger-petstore/tree/8f0dd286987880b4af7bce552aca3813166f3049>
- graph-tool-call project fixtures and MIT license:
  <https://github.com/SonAIengine/graph-tool-call/blob/main/LICENSE>
- MCP filesystem reference implementation:
  <https://github.com/modelcontextprotocol/servers/tree/d31124c982401739917fd817c2a59db344529c16/src/filesystem>

The MCP seed is explicitly recorded as a project fixture modeled after the
reference server, not as a byte-for-byte `tools/list` capture.

## WP1 Exit Criteria

WP1 is complete only when:

- OpenAPI, GraphQL, and MCP each have at least two independent API families;
- train, dev, and unopened test partitions are frozen by family;
- primary-source licensing and immutable revisions are audited;
- annotations include target, producer, alternatives, language, and origin;
- a stratified human relevance audit is prepared;
- corpus integrity passes from a clean checkout;
- the paper-readiness gate has no blocker.

The broader research questions and submission gates remain in
[`paper-readiness-design.md`](paper-readiness-design.md).
