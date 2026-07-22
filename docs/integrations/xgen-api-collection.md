# XGEN API Collection Integration

This guide captures the intended integration shape for using graph-tool-call as
the build-time and runtime search engine behind XGEN API Collections.

## Goal

XGEN should not send every API tool schema to the model. The stable path is:

1. Build an optimized collection graph when an API Collection is created or rebuilt.
2. Store the graph, readiness report, and source provenance with the collection.
3. At runtime, expose a small meta-tool surface such as `search_tools` and
   `call_tool`, or use Planflow for multi-step execution.
4. Keep XGEN-specific DB, auth, session, SSE, UI, and HTTP execution logic in
   XGEN.

graph-tool-call owns product-neutral graph construction, search evidence, IO
contract extraction, and plan synthesis metadata. XGEN owns collection storage,
user context, runtime credentials, API execution, and frontend interaction.

## Current XGEN Shape

The existing XGEN codebase already has the right attachment points:

- `xgen-workflow` has an `APICollectionLoader` node that loads a saved
  `ToolGraph` JSON and returns the `search_tools` / `call_tool` meta-tools.
- `xgen-workflow` also has an AI chat service that builds a `ToolGraph` from
  the backend gateway OpenAPI URL and exposes `graph.as_tools(top_k=...)`.
- `xgen-app-gitlab` has a Tauri sidecar path that runs the `graph-tool-call`
  CLI for `ingest`, `search`, and `call`.

The gap is version and build depth. The inspected `xgen-workflow` dependency is
still pinned to `graph-tool-call==0.19.1`, and collection build currently stores
a basic graph JSON rather than a readiness-scored, contract-rich graph with
snapshot provenance.

## Build-Time Pipeline

When XGEN builds an API Collection, the preferred library path is one call that
returns a storage-ready `ToolGraph` JSON shape plus readiness/provenance
extensions:

```python
from graph_tool_call.graphify import build_openapi_collection_artifact

artifact = build_openapi_collection_artifact(
    source,
    allow_private_hosts=True,
    context_field_names=xgen_context_field_names,
    paging_field_names=xgen_paging_field_names,
    search_filter_field_names=xgen_search_filter_field_names,
    semantic_options={
        "resource_aliases": xgen_resource_aliases,
        "module_aliases": xgen_module_aliases,
        "action_aliases": xgen_action_aliases,
    },
    promote_contract_signals=True,
)
```

The CLI exposes the same build path for job/sidecar integrations:

```bash
graph-tool-call build-openapi-collection "$SOURCE" \
  -o collection.json \
  --allow-private-hosts \
  --context-field siteNo,tenantId \
  --paging-field pageNo,pageSize \
  --search-filter-field keyword,searchWord
```

`artifact` is loadable by `ToolGraph.load()` because it keeps the normal
`graph`/`tools`/`metadata` shape. The additional top-level fields are for XGEN's
collection build table/detail UI:

The persisted collection artifact should include:

- `graph_tool_call_version`
- `collection_graph_version`
- `enrichment_status`
- `readiness_report`
- `source_snapshot_manifest`
- `semantic_summary`
- `edge_quality_summary`
- sha256 for every source spec used by the collection
- tool count, operation count, duplicate count, edge count
- coverage and issue summaries from `OpenAPICollectionReport`

The readiness report should be shown before the collection is treated as ready.
Blocker issue codes such as `missing_response_schema`,
`generic_request_body`, `duplicate_operation_id`, and
`unsupported_content_type` should block or require an explicit override.
Warnings such as `auth_required`, `response_envelope_detected`, or
`array_leaf_alignment_required`, `semantic_action_unknown_rate_high`,
`semantic_resource_unassigned_rate_high`, or `weak_edge_evidence` should be
visible in the collection detail UI. The collection graph screen should prefer
`semantic_summary.path_module_assigned_rate`, `primary_resource_assigned_rate`,
and `edge_quality_summary.visual_edge_candidate_count` for deciding whether to
show a node-level graph or a cluster map first.

## Runtime Search Path

The model-facing runtime should stay compact:

- Basic path: `search_tools(query)` returns relevant tool names, descriptions,
  parameters, and evidence; `call_tool(tool_name, arguments)` executes one API.
- Planflow path: retrieve a target, expand required producer tools, synthesize
  a plan, then execute through the XGEN adapter.

For the Planflow path, use:

```python
from graph_tool_call.graphify import (
    build_candidate_set,
    expand_candidates_with_producers,
    retrieve_graphify,
)
from graph_tool_call.plan import PathSynthesizer, PlanRunner

retrieval = retrieve_graphify(graph, query, top_k=5, include_evidence=True)
candidates = build_candidate_set(
    graph,
    query=query,
    retrieval=retrieval,
    max_target_candidates=5,
)
expanded = expand_candidates_with_producers(
    candidates["candidates"],
    graph["tools"],
    max_hops=2,
)
plan = PathSynthesizer(
    graph,
    context_defaults=context_defaults,
).synthesize(target=expanded[0], goal=query)
```

`PlanRunner.run_stream(..., trace_metadata=...)` can then forward structured
events to XGEN SSE/logging. The adapter should preserve fields such as:

- `stage`
- `plan_id`
- `step_id`
- `tool`
- `graph_tool_call_version`
- `collection_graph_version`
- `score_breakdown`
- `edge_evidence`
- `user_input_slots`
- `failed_step`

`user_input_slots` are not only labels. For OpenAPI-derived tools they may carry
`required`, `kind`, `field_type`, `location`, `json_path`, `semantic_tag`,
`schema_expanded_from`, `schema_expansion`, `content_type`, `reason`, and
`cause`. XGEN should use this metadata to render missing-field popup/resume
forms and to keep query DTO wrappers such as `mbrMgmtSearchRequest` recoverable
when leaf fields are shown to the user.

## XGEN Responsibilities

Do not move these into graph-tool-call:

- collection DB tables and file storage
- user ID, workspace ID, and tenant scoping
- cookies, bearer tokens, API keys, and credential lookup
- base URL selection and environment routing
- `execute_collection_tool` or equivalent HTTP execution adapter
- missing-field popup, resume UX, and SSE forwarding
- access-control and audit-log policy

graph-tool-call should only receive static API/tool definitions, generic field
classification options, runtime-safe context defaults, and execution callback
interfaces.

## Migration Checklist

1. Upgrade XGEN to a current exact graph-tool-call pin after a green release.
2. Add an `APICollectionBuildService` in XGEN that produces both graph JSON and
   `OpenAPICollectionReport`.
3. Persist graph/report/provenance together with the API Collection.
4. Update the collection dropdown/detail UI to show readiness, version, tool
   count, edge count, and blocker/warning counts.
5. Keep the existing `APICollectionLoader` `as_tools` path as fallback.
6. Add a Planflow API Collection path that uses evidence retrieval and producer
   expansion.
7. Replace any duplicate product-neutral helper logic in XGEN with public
   graph-tool-call APIs.
8. Add an XGEN integration smoke with an X2BEE-like fixture:
   build -> load -> search -> target selection -> plan synthesis -> mocked
   execution.
9. Add a real environment check that confirms the deployed container imports the
   expected graph-tool-call version.

## Acceptance Signals

The XGEN integration is ready when:

- collection build writes `graph_tool_call_version`,
  `collection_graph_version`, and source sha256 provenance
- readiness status is deterministic for the same source
- Korean business queries can retrieve English operation IDs and field names
- search returns compact candidate sets instead of hundreds of raw schemas
- failed planning returns structured reason codes, not exception text parsing
- runtime logs/SSE contain plan/search evidence without leaking credentials
- old collection JSON can still load through the fallback path
