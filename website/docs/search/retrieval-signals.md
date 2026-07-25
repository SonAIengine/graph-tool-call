---
title: Retrieval Signals
description: Understand the ranking evidence that contributes to graph-tool-call search results.
---

# Retrieval Signals

Retrieval should be explainable. A candidate wins because of named signals, not
because a prompt happened to prefer it.

## Core Signals

| Signal | Source |
| --- | --- |
| `keyword_match` | Tool name, operation id, summary, description |
| `action_match` | `metadata.ai_metadata.canonical_action` |
| `resource_match` | `metadata.ai_metadata.primary_resource` |
| `module_match` | `metadata.openapi.path_module` or operation group |
| `shape_match` | `metadata.ai_metadata.result_shape` |
| `contract_match` | Request and response contract fields |
| `graph_expansion` | Edges from related producers or curated links |
| `learning` | Promoted trace-learning suggestions |

## Best Practice

Use `include_evidence=True` for product debug screens and regression fixtures.
Persist only the compact evidence needed to explain the ranking. Do not store
raw secrets or full API payloads.

## Related Pages

- [Evidence Output](./evidence-output.md)
- [Target Selection](./target-selection.md)
