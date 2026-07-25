---
title: XGEN Scale Gates
description: Replay large API collection snapshots to protect enterprise catalog quality.
---

# XGEN Scale Gates

XGEN scale gates use real or replayed large API collection snapshots to verify
that graph-tool-call behaves well at enterprise catalog size. BO dev data is a
regression dataset, not a place for product-specific hard-coding.

## Why This Gate Exists

Small toy OpenAPI specs do not expose the hardest problems:

- hundreds or thousands of similar operation ids
- Korean summaries mixed with English tool names
- repeated request wrappers and response envelopes
- generic paging/search/context fields
- sibling APIs such as list/detail/count/update
- graph visualizations that become unreadable if every edge is shown

The scale gate checks whether generic engine logic still works under those
conditions.

## Core Metrics

| Metric | Target Direction |
| --- | --- |
| `canonical_action_known_rate` | high |
| `primary_resource_assigned_rate` | high |
| `path_module_assigned_rate` | high |
| `search_hit_at_8` | high |
| `search_top_1` | high |
| `selector_exact_rate` | high |
| `avg_candidate_count` | low enough for LLM context |
| `max_candidate_count` | bounded |
| `avg_schema_context_reduction` | high |
| `uncaught_server_error_count` | zero |

Project-specific thresholds should live with the fixture or Quality Lab suite.
The library should only provide generic signals and deterministic behavior.

## When To Run

| Change Type | Recommended Gate |
| --- | --- |
| Docs-only | Website build |
| Pure runner/event change | Focused runner tests |
| Retrieval scoring change | Saved snapshot replay |
| Semantic build change | Saved snapshot replay plus semantic summary gate |
| OpenAPI contract extraction change | Snapshot replay plus contract coverage gate |
| Plan synthesis change | Plan Quality Lab cases |
| Public benchmark update | Full deterministic and LLM-backed run |

## Snapshot Workflow

```bash
make xgen-scale-snapshot
```

Store the output when comparing before/after behavior:

```bash
make xgen-scale-snapshot \
  XGEN_SCALE_OUTPUT=benchmarks/results/xgen_scale_$(date +%Y%m%d).json
```

The snapshot should record the collection identity, source hash, library
version, build options, and metric summary.

## Live Sweep

Run live sweeps only when the code path touches ingest, search, semantic build,
or plan synthesis in a way that snapshot replay cannot cover.

```bash
make xgen-scale-sweep
```

Live sweeps should not be required for every documentation, UI, or small adapter
change.

## Failure Triage

| Failure | Likely Cause |
| --- | --- |
| Action known rate drops | Semantic derivation or operationId parsing changed |
| Resource assignment drops | Path/tag/resource alias handling changed |
| Candidate count grows | Graph expansion or BM25 field weighting widened too much |
| Hit@8 passes but selector exact drops | Strong-evidence selector margin or shape signal regressed |
| Plan hit drops | Contract consumes/produces or user input slot extraction regressed |
| Execute fails only live | Auth readiness, downstream API, or adapter executor issue |

## Related Pages

- [Benchmarks](./benchmarks.md)
- [Quality Lab](./quality-lab.md)
- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Target Selection](../search/target-selection.md)
