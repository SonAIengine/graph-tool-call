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

## API Collection Build

When an API collection is built, XGEN should store:

- `graph_tool_call_version`
- `collection_graph_version`
- `semantic_summary`
- `edge_quality_summary`
- `readiness_report`
- operation `metadata.openapi`
- operation `metadata.api_contract`

## Runtime

At runtime, XGEN should:

1. retrieve candidates with evidence
2. pass selector-ranked candidates to the LLM
3. guard the LLM target with `select_target_candidate`
4. synthesize the plan
5. preflight auth readiness
6. execute and save scrubbed trace evidence

