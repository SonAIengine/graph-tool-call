---
title: XGEN Integration
description: Connect graph-tool-call to XGEN API Collection build, retrieval, Planflow, execution, Quality Lab, and trace learning.
---

# XGEN Integration

XGEN should treat `graph-tool-call` as the product-neutral engine.

## Boundary

`graph-tool-call` owns:

- OpenAPI ingest and contract extraction
- semantic metadata
- graph edge normalization and evidence
- retrieval and target selection
- plan synthesis diagnostics
- scrubbed trace learning records

XGEN owns:

- DB storage
- auth profiles and user/session context
- API collection UX
- SSE/log forwarding
- real HTTP execution policy
- provider/model selection

This boundary is important. Product-specific DB/auth/session/SSE logic should
not move into the library, and generic contract/search/selector logic should not
be duplicated in XGEN.

## API Collection Build

When an API collection is built, XGEN should store:

- `graph_tool_call_version`
- `collection_graph_version`
- `semantic_summary`
- `edge_quality_summary`
- `readiness_report`
- operation `metadata.openapi`
- operation `metadata.api_contract`

## Build Flow

```text
OpenAPI source
  -> graph-tool-call contract index
  -> semantic metadata
  -> collection artifact
  -> readiness report
  -> Quality Lab search/plan cases
  -> execution enabled only when auth/readiness gates pass
```

During rebuild, preserve:

- manual `ai_metadata`
- `context_defaults`
- `enum_mappings`
- Quality Lab cases and last results
- manual/promoted trace edges
- learning suggestions and promotion status

## Runtime

At runtime, XGEN should:

1. retrieve candidates with evidence
2. pass selector-ranked candidates to the LLM
3. guard the LLM target with `select_target_candidate`
4. synthesize the plan
5. preflight auth readiness
6. execute and save scrubbed trace evidence

## LLM Provider Role

XGEN's LLM provider/model should receive a compact, selector-ranked catalog. The
provider should not receive the entire API collection unless the collection is
small enough for that to be safe.

The LLM is responsible for intent interpretation and final response generation.
The engine remains responsible for deterministic retrieval evidence, target
guardrails, plan diagnostics, and learning suggestions.

## Quality Lab Role

Quality Lab should be the operational gate for collection changes:

| Mode | Purpose |
| --- | --- |
| `search` | expected target is in Top-K |
| `plan` | target can be selected and planned |
| `execute` | adapter auth and downstream API path work safely |

Execute mode should distinguish `auth_context_required`,
`auth_profile_missing`, `auth_header_resolution_failed`, `auth_failed`,
`http_4xx`, and `http_5xx`.

## UI Requirements

XGEN should expose enough state for a non-engineer to understand a collection:

- readiness score and top issue codes
- semantic coverage
- edge quality summary
- Quality Lab cases and last run results
- target selector diagnostics
- auth readiness state
- learning suggestions in shadow/promoted/rejected states

Large graphs should open in map mode first, then scoped graph mode after a user
selects a module, resource, target, or workflow.

## Related Pages

- [OpenAPI Collections](./openapi-collections.md)
- [XGEN Quality Lab](../integrations/xgen-quality-lab.md)
- [Auth Readiness](../build/auth-readiness.md)
