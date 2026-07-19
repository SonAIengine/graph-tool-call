# Planflow Public Contract

Version: graph-tool-call 0.25.0

## graphify Contract

The graphify package owns product-neutral collection graph logic.

- `ingest_openapi_graphify(schemas)` builds a `ToolGraph` with confidence-labeled edges.
- `ingest_openapi_graphify(..., promote_contract_signals=True)` selectively promotes
  OpenAPI `metadata.api_contract` rows into search/planning IO signals and derives
  `REQUIRES` data-flow edges.
- `build_io_contract(...)` produces plain `metadata.produces` and `metadata.consumes` lists from schema fragments and caller-provided field classifiers.
- `promote_api_contract_signals(...)` applies the same product-neutral contract
  promotion policy independently when callers want to inspect or persist the
  enriched tool metadata before graph build.
- Promoted raw OpenAPI contract rows default to `search_signal=False`; they are
  planning/producer signals unless the caller deliberately opts into BM25 field
  indexing.
- BM25 indexes parameter descriptions plus curated/indexable field descriptions,
  aliases, and enum values. Example-derived object parameters can therefore
  match XGEN-style field queries such as `goodsNo` / "상품번호" without indexing
  every raw OpenAPI leaf.
- OpenAPI3 parameter `content` schemas are carried as additive `content_type`,
  `content_fields`, and `content_types` hints so search, planning, validation,
  and execution share the same wire contract.
- Nullable request/response fields are normalized across OpenAPI `nullable`,
  Swagger `x-nullable`, JSON Schema null type arrays, and single-schema null
  unions, then preserved as `nullable=true` contract hints.
- OpenAPI success-response links are normalized into `api_contract.links`,
  promoted as `openapi_link` graph evidence, and may add non-search producer
  aliases when the response field name differs from the linked parameter name.
- `additionalProperties` map leaves are represented additively with
  `additional_properties`, `map_value`, and `map_key_placeholder` hints; map
  value paths use `*` as a sorted-key first-value placeholder, not fan-out.
- `expand_candidates_with_producers(...)` expands retrieval candidates with deterministic 1-hop producers for required `kind=data` inputs.
- `normalize_graph_edge(...)`, `merge_graph_edges(...)`, and `derive_plan_trace_edges(...)` normalize structural, LLM-curated, manual, and run-observed signals into graph version 2 edge metadata.
- `retrieve_graphify(..., include_evidence=True)` keeps the legacy response keys and adds score/evidence details for logs and UI.

## Plan Synthesis Contract

`PathSynthesizer` remains transport-agnostic. It only reads a serialized graph dict and emits a `Plan`.

- `kind=data` inputs can be filled from entities, producer chains, or `user_input` slots.
- `kind=context` and `kind=auth` inputs are ambient. They are filled from
  entities or context defaults when available and are never producer-chained.
  OpenAPI security schemes are represented as `kind=auth` consumes with scheme
  metadata; runtime token/cookie/header values remain the caller's concern.
- OpenAPI success-response headers can appear as producer rows with
  `location=response_header` and `json_path=$.headers.<Name>`. Header-based
  OpenAPI links therefore bind as `${sN.headers.<Name>}`.
- Producer rows with OpenAPI response envelope hints can bind through
  `HttpExecutor`'s schema-guided `body_view`, for example
  `${sN.body_view.value[0].goodsNo}` for `$.data.items[*].goodsNo`.
- `PlanSynthesisError.to_dict()` exposes `stage`, `reason`, `message`, and structured details so adapters do not need to parse exception text.
- `Plan.metadata.synthesis` records `target`, selected producers, candidate signals, and user-input fallbacks.

## Runner Event Contract

`PlanRunner.run_stream(plan, trace_metadata=None)` still yields dataclass events.

Every event includes additive metadata fields:

- `stage`
- `plan_id` where applicable
- `graph_tool_call_version`
- `trace_metadata`

Adapters can forward `asdict(event)` directly to SSE or logs.
