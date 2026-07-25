---
title: OpenAPI Collections
description: Build large OpenAPI surfaces into searchable, plannable, executable tool graph artifacts.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# OpenAPI Collections

An OpenAPI collection is a stored tool catalog built from one or more Swagger
or OpenAPI sources. Use it when an agent needs to search, plan, and execute over
a large API surface without sending every endpoint to the LLM.

Treat the collection as a build artifact, not a raw endpoint list. A useful
artifact contains normalized tools, request/response contracts, deterministic
semantic metadata, graph edges, readiness diagnostics, validation results, and
provenance.

## Collection Lifecycle

```text
register source
  -> build artifact
  -> inspect readiness
  -> run search/plan quality cases
  -> enable execute
     when auth and safety are ready
  -> preserve manual metadata
     and learning metadata during rebuild
```

The engine owns product-neutral graph evidence. Your application owns source
storage, auth profiles, tenant policy, UI, execution, audit logging, and
operator approvals.

## When To Use This Guide

Use this guide when:

- one API source has hundreds or thousands of operations
- the OpenAPI document comes from Swagger UI, JSON, YAML, or multiple specs
- operation names are mixed across Korean, English, RPC-style names, and path
  modules
- search quality depends on fields, response shape, auth, or workflow order
- a product UI must explain collection quality before users run API calls
- rebuilds must preserve manual metadata, Quality Lab cases, or promoted trace
  learning suggestions

For a single quick search, start with [OpenAPI Ingestion](../build/openapi-ingestion.md).
For a product-facing stored catalog, use this collection workflow.

## Recommended Pipeline

| Stage | Engine Output | Product Decision |
| --- | --- | --- |
| Source registration | source manifest and discovered spec URLs | where the source is stored and who may refresh it |
| Contract extraction | `api_contract.consumes`, `produces`, `links` | whether missing schemas need repair before execute |
| Semantic build | action/resource/module/result-shape metadata | whether aliases or manual curation are needed |
| Graph build | structural, contract, semantic, manual, trace edges | which edge types are visible and which affect ranking |
| Readiness | score, status, issue codes, recommendations | whether search, plan, or execute is enabled |
| Validation | Quality Lab and benchmark results | whether to promote the artifact |
| Rebuild | new source-derived facts plus preserved product fields | whether source changes are compatible |

## Build The Artifact

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
graph-tool-call \
  build-openapi-collection \
  openapi.json \
  -o collection.json \
  --context-field tenantId,siteNo \
  --paging-field page,size \
  --search-filter-field keyword,searchText
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
)

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"tenantId", "siteNo"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchText"},
    metadata={"collection_id": "commerce-readonly"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

  </TabItem>
  <TabItem value="multiple" label="Multiple specs">

```python
artifact = build_openapi_collection_artifact(
    [
        "orders.openapi.json",
        "members.openapi.json",
        "payments.openapi.json",
    ],
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)
```

  </TabItem>
</Tabs>

Pass product naming conventions as options. Do not add customer-specific field
dictionaries to the library.

## Artifact Sections

| Section | Purpose |
| --- | --- |
| `graph` | Serialized graph payload compatible with `ToolGraph.load()` |
| `tools` | Normalized `ToolSchema` rows keyed by tool name |
| `metadata` | build options, source identity, version, summary copies |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | evidence distribution for graph edges |
| `readiness_report` | deterministic OpenAPI readiness diagnostics |
| `source_snapshot_manifest` | source labels, URLs, hashes, operation counts |
| `ingest_summary` | duplicate handling and operation counts |
| `quality_lab` | optional product-side search/plan/execute cases |
| `learning` | optional scrubbed trace-learning attempts and suggestions |

Store the whole artifact. If you persist only `graph`, the product loses the
diagnostics needed to explain readiness and rebuild behavior.

## Contract Index

Use `extract_openapi_contract_index()` when an adapter needs operation-level
facts before or outside a full graph build.

```python
from graph_tool_call.graphify import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")

for operation in index["operations"]:
    print(
        operation["method"],
        operation["path"],
        operation["operationId"],
        operation["content_types"],
        operation["security"],
    )
```

The contract index is useful for source preview, contract repair, migration
checks, and UI diagnostics. Runtime credentials do not belong in this object.

## Readiness Gate

Run readiness immediately after build and after every source refresh.

```python
summary = artifact["readiness_report"]["summary"]
issues = artifact["readiness_report"]["issues"]

if summary["status"] == "blocked":
    disable_execute()

print(summary["readiness_score"])
print(issues[:5])
```

Stable issue codes include:

| Code | Meaning | Typical Action |
| --- | --- | --- |
| `missing_request_schema` | request fields are not visible | repair source or add adapter metadata |
| `generic_request_body` | body is too generic to plan safely | refine schema or require user input |
| `missing_response_schema` | result fields cannot be produced | add response schema or body view mapping |
| `duplicate_operation_id` | tool names may collide | repair operation ids or source labels |
| `missing_operation_id` | stable identity is weak | derive names from method/path and preserve mapping |
| `auth_required` | execution needs adapter auth | configure auth profile and session header resolution |
| `unsupported_content_type` | body type cannot be modeled | add execution adapter handling |
| `array_leaf_alignment_required` | nested array/body alignment is uncertain | validate body view extraction |
| `response_envelope_detected` | result is wrapped under an envelope | pick the useful body view before planning |
| `low_graph_connectivity` | producer expansion has weak evidence | inspect contracts and edge quality |
| `no_contract_fields` | neither consumes nor produces were extracted | repair schemas before plan/execute |

Warnings can still allow search. Blockers should prevent execute until the
adapter has a deliberate override.

## Search And Target Selection

After the artifact exists, use graph retrieval to create a small candidate set.
Use target selection to guard the LLM's final target choice.

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import (
    retrieve_graphify,
    select_target_candidate,
)

graph = ToolGraph.load("collection.json")
retrieval = retrieve_graphify(
    graph,
    "find refund-ready orders",
    top_k=8,
    include_evidence=True,
)

selection = select_target_candidate(
    query="find refund-ready orders",
    candidates=[row["name"] for row in retrieval["results"]],
    tools=graph.tools,
    retrieval_results=retrieval["results"],
    llm_target=llm_intent.target,
)

print(selection["selected_target"])
print(selection["candidate_evidence"])
```

The product should store enough evidence to debug bad outcomes:

- query text or query fingerprint
- retrieval Top-K and score breakdown
- LLM target
- selector target
- override flag and reason codes
- selected tool contract summary

## Plan And Execute Gate

Execution should be enabled only after search and plan quality are known.

Require:

- readiness report has no blocker issue
- representative search cases pass Top-K targets
- target selector diagnostics are visible
- representative plan cases synthesize expected steps
- auth readiness can resolve runtime headers
- write tools have mutation safety and cleanup policy

Read-only cases can be used earlier. Mutating cases should require an explicit
allowlist, confirmation, cleanup steps, and assertions.

## Rebuild Policy

Source refresh should not delete product-owned metadata.

Preserve:

- manually curated `ai_metadata`
- `context_defaults`
- `enum_mappings`
- manual edges and promoted trace edges
- Quality Lab cases and last summaries
- learning suggestions with `suggested`, `promotable`, `promoted`, or
  `rejected` status
- auth profile references and execution policy

Recompute:

- source-derived tools and schemas
- deterministic semantic metadata when not manually overridden
- contract fields
- readiness report
- weak structural/name-based edges
- edge quality summary

If the new source removes a promoted target, mark the preserved evidence stale
instead of silently applying it.

## UI Checklist

A product UI should make collection quality obvious before execution:

- source URL, source count, tool count, graph version
- readiness score and top blocker/warning issues
- semantic coverage and unknown samples
- edge quality summary
- auth readiness state
- Quality Lab last run result
- target selector evidence for failed cases
- map view for large catalogs and scoped graph for selected modules/tools
- rebuild history and preserved manual changes

For large collections, avoid rendering every edge by default. Start with map
summaries and render detailed graph edges only after the user scopes down to a
module, resource, target, or workflow path.

## Adapter Responsibilities

The engine builds product-neutral evidence. The application owns:

- DB rows and collection lifecycle
- source access permissions and tenant policy
- auth profile and runtime session headers
- model/provider routing
- UI for readiness, graph, Quality Lab, and learning results
- safe execution policy and audit logging
- manual operator overrides
- preserving product fields during rebuild

Never store raw tokens, cookies, API keys, session ids, or user identifiers in
graph artifacts, learning records, or public diagnostics.

## Related Pages

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Collection Artifacts](../build/collection-artifacts.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Tool Graph](../concepts/tool-graph.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
