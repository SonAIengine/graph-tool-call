# Python API Reference

The primary entry point is `ToolGraph`. Most workflows are: ingest a spec → call `retrieve()`.

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("api.json")
tools = tg.retrieve("create a pet", top_k=5)
```

---

## `ToolGraph` methods

### Construction

| Method | Description |
|---|---|
| `ToolGraph()` | Empty graph |
| `ToolGraph.from_url(url, cache=...)` | Build from Swagger UI or spec URL (auto-discovers spec groups) |
| `ToolGraph.load(path)` | Deserialize from JSON |

### Ingestion

| Method | Description |
|---|---|
| `add_tool(tool)` | Add a single tool (auto-detects format) |
| `add_tools(tools)` | Add multiple tools |
| `ingest_openapi(source)` | Ingest from OpenAPI / Swagger spec (file path, URL, or dict) |
| `ingest_mcp_tools(tools)` | Ingest from MCP tool list |
| `ingest_mcp_server(url)` | Fetch and ingest from an MCP HTTP server |
| `ingest_functions(fns)` | Ingest from Python callables (uses type hints + docstrings) |
| `ingest_arazzo(source)` | Ingest Arazzo 1.0.0 workflow spec |
| `add_relation(src, tgt, type)` | Add a manual relation between two tools |

### Retrieval

| Method | Description |
|---|---|
| `retrieve(query, top_k=10)` | Search and return tool list |
| `retrieve_with_scores(query, top_k=10)` | Search and return tools with confidence scores and relation hints |
| `plan_workflow(query)` | Build an ordered execution plan |
| `suggest_next(tool, history=...)` | Suggest next tools based on graph relations |
| `validate_tool_call(call)` | Validate and auto-correct a tool call |
| `assess_tool_call(call)` | Return `allow` / `confirm` / `deny` decision based on annotations |

### Configuration

| Method | Description |
|---|---|
| `enable_embedding(provider)` | Enable hybrid embedding search (Ollama, OpenAI, vLLM, sentence-transformers, callable) |
| `enable_reranker(model)` | Enable cross-encoder reranking |
| `enable_diversity(lambda_)` | Enable MMR diversity |
| `set_weights(keyword=, graph=, embedding=, annotation=)` | Tune wRRF fusion weights |
| `auto_organize(llm=...)` | Auto-categorize tools (rule-based or LLM-enhanced) |
| `build_ontology(llm=...)` | Build complete ontology |

### Analysis

| Method | Description |
|---|---|
| `find_duplicates(threshold)` | Find duplicate tools across sources |
| `merge_duplicates(pairs)` | Merge detected duplicates |
| `apply_conflicts()` | Detect and add `CONFLICTS_WITH` edges |
| `analyze()` | Build operational analysis summary |

### Persistence

| Method | Description |
|---|---|
| `save(path)` | Serialize to JSON (preserves embeddings + weights when set) |
| `ToolGraph.load(path)` | Deserialize and restore retrieval state |

### Export & visualization

| Method | Description |
|---|---|
| `export_html(path, progressive=True)` | Interactive HTML (vis.js) |
| `export_graphml(path)` | GraphML for Gephi / yEd |
| `export_cypher(path)` | Neo4j Cypher statements |
| `dashboard_app()` | Build Dash Cytoscape app object |
| `dashboard(port=8050)` | Launch interactive dashboard |

### Execution

| Method | Description |
|---|---|
| `execute(name, params, base_url=...)` | Execute an OpenAPI tool directly |
| `HttpExecutor.validate_request(tool, params)` | Preflight an OpenAPI request without network I/O |

OpenAPI ingest preserves execution-oriented request/response facts in each
tool's metadata:

- `ToolSchema.name`: unique executable/search tool name. OpenAPI `operationId`
  is preserved as-is when unique; duplicate `operationId` values are deduped
  with a deterministic method/path suffix such as
  `findOrder__get_orders_by_orderId`.
- `metadata.openapi.operation_id`: original OpenAPI operationId, even when
  `ToolSchema.name` was deduped. Duplicate groups include
  `operation_id_duplicate_count`, `operation_id_duplicate_index`, and
  `operation_id_deduped_name` when applicable.
- `metadata.openapi.parameters`: normalized path/query/header/cookie parameters,
  including serialization hints such as `style`, `explode`, `allowReserved`,
  schema defaults, examples, and validation constraints
- `metadata.openapi.request_body`: selected content type, all declared content
  type candidates, candidate-level fields, schema, top-level fields, leaf
  fields, and body examples. If schema fields are missing but concrete examples
  exist, inferred fields are included with `schema_inferred_from=example`.
  Non-property JSON bodies such as root arrays, primitive payloads, and opaque
  map bodies also include `root` with `request_body_root=true` and a synthetic
  executable `body` slot, while leaf fields remain available for graph/plan
  contracts. JSON object request bodies can also be executed by passing an
  explicit raw `body` object when no schema field is named `body`.
- `metadata.openapi.response`: selected success status, content type, schema,
  description, leaf fields, declared response headers, optional response
  envelope metadata, and selected OpenAPI response links
- `metadata.openapi.responses`: compact catalog of every declared response,
  including status, success flag, content types, examples, headers, links, and
  field count. Numeric 2xx and `2XX` status ranges are classified as success;
  `4XX`/`5XX` ranges and `default` remain failure metadata.
- `metadata.openapi.error_responses`: non-2xx response catalog for failure UI/logs
- `metadata.openapi.server`: effective OpenAPI server metadata, preserving
  the raw URL template, default-expanded URL, variable defaults/enums, selected
  source (`operation`, `path`, `spec`, or `swagger2`), and same-scope server
  candidates
- `metadata.openapi.security`: declared security requirements and static scheme
  metadata, without runtime credentials
- `metadata.api_contract`: raw extracted produces/consumes rows for graph building.
  Declared OpenAPI security requirements are also exposed as
  `consumes[].kind=auth` rows with `security_schemes`, `auth_type`,
  `credential_name`, and `security_required`; runtime secret values stay in the
  caller/executor layer.

OpenAPI field direction is enforced before graph/search promotion:

- request-body consumes exclude `readOnly` fields and preserve `writeOnly`
  fields as request-only hints
- response produces exclude `writeOnly` fields and preserve `readOnly` fields
  as response-only hints
- nested object/array leaves inherit parent `readOnly`, `writeOnly`, and
  `deprecated` hints
- Nullable dialects are normalized before contract extraction. OpenAPI
  `nullable`, Swagger `x-nullable`, JSON Schema `type: ["T", "null"]`, and
  single-schema `anyOf` / `oneOf` null unions are exposed as `nullable=true`.
- OpenAPI3 query object wrappers are expanded into their real inner fields for
  `metadata.openapi.parameters`, `input_locations`, and `api_contract.consumes`.
- Root JSON array request bodies can be executed either by passing raw
  `{"body": [...]}` or, for a single array item, by passing the extracted item
  leaf arguments; the executor emits the array body instead of inventing an
  object wrapper.
- Nested object/array request fields can also be satisfied by extracted leaf
  arguments. For example `$.items[*].goodsNo` plus `$.items[*].quantity` is
  rendered as `{"items": [{"goodsNo": "...", "quantity": 1}]}`, and required
  container fields are not reported missing when their leaf fields are present.
- OpenAPI parameter/body `default` values and JSON Schema `const` values are
  applied as executable defaults when the caller omits a non-path input. User
  supplied values are never overwritten, declared `apiKey` security credentials
  and credential-like names such as `Authorization`, `access_token`, or
  `X-Api-Key` are excluded, and `example` values are not used as live request
  data.
- Declared success-response headers are exposed as `api_contract.produces` rows
  with `location=response_header` and `json_path=$.headers.<Name>`, so cursor,
  `Location`, `ETag`, and token-like handoff headers can participate in
  graph/search/plan contracts.
- OpenAPI response status ranges are preserved. A `2XX` response can be the
  selected success contract for produces/Planflow, while `4XX`/`5XX` rows stay
  in `metadata.openapi.error_responses` for failure UX and logs.
- OpenAPI `servers[].variables` are expanded with their declared defaults for
  `metadata.base_url`, while the raw template and variable enum/default
  metadata remain under `metadata.openapi.server`. Server priority follows
  OpenAPI rules: operation-level, then path-level, then spec-level. Link Object
  `server` entries use the same default expansion and are preserved on the link
  row.
- Declared OpenAPI `security` schemes are converted to ambient auth consumes.
  `apiKey` schemes use their declared query/header/cookie credential name;
  bearer/basic/OAuth/OpenID Connect schemes use `Authorization` as the
  credential field. These rows are `kind=auth` and remain non-user-input plan
  dependencies.
  If Spring/SpringDoc exposes both the wrapper and a sibling field, the wrapper
  is dropped and the sibling wins. Explicit `style=deepObject` parameters keep
  the wrapper because it is part of the wire format.
- OpenAPI3 parameter `content` schemas are preserved for path/query/header/cookie
  parameters. Selected JSON content parameters expose `content_type`,
  `content_fields`, and `content_types` evidence while keeping the parameter
  name as the wire-level input.
- JSON Schema `additionalProperties` maps preserve map-value fields with
  `additional_properties=true`, `map_value=true`, and `map_key_placeholder="*"`.
  Object map values use paths such as `$.data.*.goodsNo`; primitive maps keep
  the parent field name with paths such as `$.labels.*`. Runtime `*` selection
  uses the first map key after string sorting.
- `oneOf` / `anyOf` schemas are expanded across all object branches instead of
  only the first branch; branch-local required fields are marked with
  `required_in_branch` and do not become global request requirements
- discriminator mappings and JSON Schema `const` values are preserved as
  `discriminator_property`, `discriminator_value`, `discriminator_values`,
  `schema_ref`, and `const`; when a discriminator field is omitted from branch
  schemas, a synthetic top-level body field is still exposed for execution
- common response envelopes such as `code/message/data` are detected as
  `metadata.openapi.response.envelope`; response fields and `api_contract`
  produces preserve `response_envelope_path`, `response_collection_path`,
  `response_item_path`, and `value_path_aliases`
- OpenAPI response `links` are preserved under `metadata.openapi.responses`
  and `metadata.api_contract.links`. Graphify turns success-response links
  into explicit `openapi_link` evidence edges and link-derived producer aliases
  for mappings such as `$response.body#/id -> userId`.
- example-inferred request/response fields are additive and marked with
  `example_source`, `example_name`, `example_content_type`, and
  `example_status` when available; they are not treated as globally required

`HttpExecutor` uses this metadata before falling back to method-based heuristics,
so POST operations with query/header parameters are rendered correctly. It also
honors common OpenAPI parameter serialization rules such as `form`,
`spaceDelimited`, `pipeDelimited`, `deepObject`, `simple`, `label`, `matrix`,
`explode`, and `allowReserved`. JSON parameter `content` values are serialized
as one encoded parameter value instead of exploded object fields. Nested
`deepObject` query filters are rendered with deterministic bracket notation
such as `filter[range][minPrice]=1000`; primitive arrays repeat the same
bracketed field name and structured arrays use numeric indexes. For request
bodies it preserves declared media type candidates and can render `application/json`,
`application/x-www-form-urlencoded`, and `multipart/form-data`; binary/file-like
arguments select the multipart candidate when one is declared. OpenAPI
`requestBody.content[media].encoding` is preserved as field-level
`encoding_*` metadata; urlencoded fields honor explicit `style` / `explode` /
`allowReserved` hints, and multipart parts use declared part `contentType` and
static/default/example part headers when available. For multipart object parts,
nested leaf arguments can be grouped back into the encoded top-level part, e.g.
`title` / `category` under `$.metadata.*` become one `metadata` JSON part.
Other declared request-body media types such as `text/plain` and
`application/octet-stream` are sent as raw body bytes rather than JSON-wrapped
payloads; the synthetic root `body` slot is used when present.
By default, `HttpExecutor` applies OpenAPI `default` and JSON Schema `const`
values for omitted non-path parameters and request-body fields before validation
and request rendering. Defaults are not applied to declared `apiKey` security
credentials or credential-like parameter names such as `Authorization`,
`access_token`, and `X-Api-Key`; runtime auth must still come from executor
headers/cookies or explicit caller arguments. Pass `apply_defaults=False` to
keep strict caller-only execution. Applied values are reported in
`validate_request()` diagnostics.

`HttpExecutor.validate_request(tool, params)` returns structured preflight
diagnostics for XGEN popup/resume flows:

- `valid`: false when required inputs, declared security credentials, or
  provided argument values fail the OpenAPI contract
- `missing_required`: required path/query/header/cookie/body inputs with
  location, source, JSON path, enum, and schema hints when available
- `missing_security`: unsatisfied OpenAPI security alternatives. Each row keeps
  the requirement index and missing scheme names, credential locations, and
  credential names without including runtime credential values
- `invalid_arguments`: provided path/query/header/cookie/body values that
  violate schema hints such as const, enum, type, numeric bounds, string
  length, pattern, array item count, object property count, or multiple-of
  constraints. JSON request body validation applies to both leaf arguments and
  explicit raw JSON `body` payloads, including root-array bodies and nested
  array item fields addressed by wildcard JSON paths such as `$[*].quantity`
  or `$.items[*].goodsNo`. Discriminator-selected request bodies also reject
  fields that belong only to another branch with
  `reason=discriminator_branch`.
- branch-local missing fields are reported as `source=request_body_branch` when
  the caller supplied a discriminator value that selects that branch
- explicit JSON body `None` values are treated as present body fields; nullable
  fields serialize as JSON `null`, while non-nullable fields fail with
  `reason=null`
- `unused_arguments`: provided arguments that are not part of the tool contract
- `used_arguments`: classified path/query/header/cookie/body argument names
- `selected_content_type`: request body media type selected from OpenAPI metadata
- `applied_defaults`: OpenAPI `default` / JSON Schema `const` values applied
  before validation and rendering, with location, source, and value metadata

For JSON request bodies, field-level arguments are rendered through their
OpenAPI `json_path`. Nested object fields such as `$.shipping.city` become
`{"shipping": {"city": ...}}`; root or nested array item paths such as
`$[*].goodsNo` and `$.items[*].quantity` can accept equal-length leaf lists and
render row-wise array items. The same item values are checked by preflight
validation before network I/O.

By default, `build_request()` and `execute()` raise
`OpenAPIRequestValidationError` before network I/O when required inputs,
declared security credentials, or invalid argument values would make the request
contract-invalid. `apiKey` security schemes can be supplied through matching
query/header/cookie arguments or executor headers; HTTP bearer/basic and
OAuth/OpenID Connect schemes are validated from the `Authorization` header,
including the `auth_token=` shortcut for bearer tokens. Pass
`validate_values=False` to keep missing-required/security blocking while
allowing server-side value coercion, or `validate_required=False` for fully
diagnostic-only or legacy partial-request behavior. `validate_request()` still
returns all diagnostics either way.

Execution results keep the legacy `status`, `headers`, and `body` keys and add
response diagnostics:

- `ok`: HTTP 2xx boolean
- `content_type`: response media type without parameters
- `response_metadata`: the matched OpenAPI response catalog row, using exact
  status, `2XX`-style range, then `default`
- `body_view`: optional schema-guided view for OpenAPI response envelopes.
  When ingest detects wrappers such as `code/message/data` or collection paths
  such as `$.data.items[*]`, `body_view.value` contains the payload or item
  list while preserving the raw response under `body`.
- `error_response`: the matched non-success response row for HTTP errors

For graph/search use, keep raw contract and promoted signal separate. Large
Swagger specs often repeat wrapper fields such as `status`, `data`, and `list`,
so plain ingest does not index every leaf. Use graphify promotion when you want
selected contract fields to participate in producer expansion and plan synthesis:

```python
from graph_tool_call.graphify import ingest_openapi_graphify
from graph_tool_call.ingest.openapi import ingest_openapi

tools, _ = ingest_openapi(spec)
tg, stats = ingest_openapi_graphify(
    tools,
    raw_spec=spec,
    promote_contract_signals=True,
    context_field_names={"siteNo"},
    paging_field_names={"pageNo", "pageSize"},
)
```

The promotion step adds high-value fields to `metadata.produces` /
`metadata.consumes`, classifies `kind=data|context|auth`, and derives
`consumer --requires--> producer` data-flow edges with `api_contract` evidence.
OpenAPI response links add `openapi_link` evidence and can bridge mismatched
field names, for example a producer response `id` or response header
`X-Session-Token` feeding a consumer `userId` or `sessionToken`.
Promoted raw contract rows set `search_signal=False` by default so target-tool
BM25 ranking is not flooded by identifier fields. Turn indexing on only for a
controlled experiment or a curated collection.
BM25 still indexes parameter descriptions and curated/indexable field metadata,
including aliases and enum values. This lets example-derived object parameters
such as `filters` match field-level queries like `brandNo` / "브랜드번호"
without turning every raw contract leaf into a search token.

---

## Top-level helpers

| Function | Description |
|---|---|
| `filter_tools(tools, query, top_k=5)` | One-shot filter on any tool list (LangChain, OpenAI, MCP, Anthropic, callables) |
| `GraphToolkit(tools, top_k=5)` | Reusable toolkit — build graph once, filter per query |

## Middleware

| Function | Description |
|---|---|
| `patch_openai(client, graph, top_k=5)` | Auto-filter tools on OpenAI client |
| `patch_anthropic(client, graph, top_k=5)` | Auto-filter tools on Anthropic client |

## LangChain

| Function | Description |
|---|---|
| `create_gateway_tools(tools, top_k=10)` | Convert N tools → 2 gateway meta-tools |
| `create_agent(llm, tools, top_k=5)` | Auto-filtering LangGraph agent |
| `GraphToolRetriever(tool_graph, top_k=5)` | LangChain `BaseRetriever` returning `Document` objects |
| `tool_schema_to_openai_function(tool)` | Convert `ToolSchema` → OpenAI function dict |

---

## Embedding provider strings

`enable_embedding()` accepts:

| Form | Example |
|---|---|
| `"ollama/<model>"` | `"ollama/qwen3-embedding:0.6b"` |
| `"openai/<model>"` | `"openai/text-embedding-3-large"` |
| `"vllm/<model>"` | `"vllm/Qwen/Qwen3-Embedding-0.6B"` |
| `"vllm/<model>@<url>"` | `"vllm/model@http://gpu-box:8000/v1"` |
| `"llamacpp/<model>@<url>"` | `"llamacpp/model@http://192.168.1.10:8080/v1"` |
| `"<url>@<model>"` | `"http://localhost:8000/v1@my-model"` |
| `"sentence-transformers/<model>"` | `"sentence-transformers/all-MiniLM-L6-v2"` |
| `callable` | `lambda texts: my_embed_fn(texts)` |

## Ontology LLM inputs

`auto_organize(llm=...)` accepts:

| Input | Wrapped as |
|---|---|
| `OntologyLLM` instance | Pass-through |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAI client (has `chat.completions`) | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completion wrapper |
