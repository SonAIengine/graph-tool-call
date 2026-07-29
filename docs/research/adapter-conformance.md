# E0 Adapter Conformance

The E0 benchmark measures whether built-in ingest adapters preserve
source-declared executable facts before retrieval or an LLM is involved. It is
a deterministic normalization test, not a tool-selection or API-execution
benchmark.

## Run

```bash
make paper-adapter-conformance
```

The default run evaluates the frozen public `train,dev` partitions and writes a
schema-v1 experiment artifact to:

```text
/tmp/graph-tool-call-adapter-conformance.json
```

Override inputs without changing the runner:

```bash
SPLITS=train \
OUT=/tmp/adapter-train.json \
make paper-adapter-conformance

poetry run python -m benchmarks.experiment.cli validate \
  /tmp/adapter-train.json
```

The held-out `test` partition is rejected unless explicitly unlocked, and it
must remain unopened while evaluator or adapter behavior is being tuned.

## Expectation Boundary

The evaluator reads each raw source independently from the adapter under test.
Operations are matched with source-stable identities:

- OpenAPI: `METHOD path`
- GraphQL: `operation_type:root_field`
- MCP: tool name

Only facts explicitly present in a source enter a denominator. For example, an
MCP tool without `outputSchema` is `N/A` for response preservation rather than
a failure. Missing optional auth is also `N/A`.

Schema comparison uses bounded concrete leaf path/type signatures. Recursive
references, unresolved references, and facts beyond the depth bound are not
invented as `unknown` failures. A richer resolved schema therefore does not
fail merely because it expands an opaque source node.

## Metrics

| Metric | Applicable unit | Pass condition |
|---|---|---|
| request schema preservation | operation with request fields or body schema | all declared parameter names and bounded body signatures remain |
| response schema preservation | operation with an output schema | all bounded output signatures remain |
| auth/security preservation | operation with declared or required security | scheme declarations, requirements, and auth contract rows remain |
| execution template generation | normalized operation | transport-specific call information is buildable |
| `api_contract.consumes` extraction | operation with actionable request/auth facts | all independently inspectable consume field names and required auth schemes remain |
| `api_contract.produces` extraction | operation with actionable response facts | all independently inspectable produce field names remain |
| deterministic serialization/replay | source document | two ingests serialize identically and JSON round-trip exactly |
| structured unsupported diagnostics | negative probe | expected stable exception or blocker issue code is returned |

The artifact reports both:

- **micro rate:** total passed operations divided by total applicable
  operations;
- **macro rate:** mean per-source rate over sources where the metric applies.

Failure samples retain source and operation identities. Raw credentials,
request bodies, and response bodies are not recorded.

## Structured Negative Probes

The fixed probe suite verifies:

1. unsupported required capability for OpenAPI;
2. unsupported required capability for GraphQL;
3. unsupported required capability for MCP;
4. unknown source detection;
5. missing GraphQL endpoint diagnostics; and
6. empty MCP catalog diagnostics.

An unsupported input must never be reported as silently ready.

## Current Development Result

The 2026-07-30 train/dev pilot covered five frozen sources and 291 normalized
tools across OpenAPI, GraphQL introspection, and MCP:

| Metric | Passed / applicable | Micro | Macro |
|---|---:|---:|---:|
| request schema preservation | 288 / 288 | 1.000 | 1.000 |
| response schema preservation | 266 / 266 | 1.000 | 1.000 |
| auth/security preservation | 267 / 267 | 1.000 | 1.000 |
| execution template generation | 291 / 291 | 1.000 | 1.000 |
| `api_contract.consumes` extraction | 287 / 287 | 1.000 | 1.000 |
| `api_contract.produces` extraction | 266 / 266 | 1.000 | 1.000 |
| deterministic serialization/replay | 5 / 5 | 1.000 | 1.000 |
| structured unsupported diagnostics | 6 / 6 | 1.000 | N/A |

This is development evidence only. It does **not** establish support for every
OpenAPI dialect, every MCP server, every GraphQL schema, or actual execution
success. The public corpus is still small, the held-out family remains
unopened, and independent corpus review remains a publication blocker.

The pilot contains 267 OpenAPI tools, four GraphQL tools, and 20 MCP tools.
The current MCP snapshots do not declare `outputSchema`, so MCP response and
produce preservation are `N/A` in this table; optional MCP output preservation
is covered by synthetic contract tests until another independently sourced
fixture is added.

## Adding An Adapter

A new source adapter is not considered supported merely because it emits
`ToolSchema` objects. Add an independently inspected public fixture and make
the same metrics applicable. Product- or customer-specific names must not enter
the evaluator or engine.

The adapter SPI and issue taxonomy are documented in
[Universal Ingest Adapters](../design/universal-ingest-adapters.md).
