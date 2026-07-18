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

- `metadata.openapi.parameters`: normalized path/query/header/cookie parameters,
  including serialization hints such as `style`, `explode`, `allowReserved`,
  schema defaults, examples, and validation constraints
- `metadata.openapi.request_body`: selected content type, all declared content
  type candidates, candidate-level fields, schema, top-level fields, leaf
  fields, and body examples. If schema fields are missing but concrete examples
  exist, inferred fields are included with `schema_inferred_from=example`
- `metadata.openapi.response`: selected success status, content type, schema,
  description, leaf fields, and optional response envelope metadata
- `metadata.openapi.responses`: compact catalog of every declared response,
  including status, success flag, content types, examples, and field count
- `metadata.openapi.error_responses`: non-2xx response catalog for failure UI/logs
- `metadata.openapi.security`: declared security requirements and static scheme
  metadata, without runtime credentials
- `metadata.api_contract`: raw extracted produces/consumes rows for graph building

OpenAPI field direction is enforced before graph/search promotion:

- request-body consumes exclude `readOnly` fields and preserve `writeOnly`
  fields as request-only hints
- response produces exclude `writeOnly` fields and preserve `readOnly` fields
  as response-only hints
- nested object/array leaves inherit parent `readOnly`, `writeOnly`, and
  `deprecated` hints
- OpenAPI3 query object wrappers are expanded into their real inner fields for
  `metadata.openapi.parameters`, `input_locations`, and `api_contract.consumes`.
  If Spring/SpringDoc exposes both the wrapper and a sibling field, the wrapper
  is dropped and the sibling wins. Explicit `style=deepObject` parameters keep
  the wrapper because it is part of the wire format.
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
- example-inferred request/response fields are additive and marked with
  `example_source`, `example_name`, `example_content_type`, and
  `example_status` when available; they are not treated as globally required

`HttpExecutor` uses this metadata before falling back to method-based heuristics,
so POST operations with query/header parameters are rendered correctly. It also
honors common OpenAPI parameter serialization rules such as `form`,
`spaceDelimited`, `pipeDelimited`, `deepObject`, `simple`, `label`, `matrix`,
`explode`, and `allowReserved`. For request bodies it preserves declared media
type candidates and can render `application/json`,
`application/x-www-form-urlencoded`, and `multipart/form-data`; binary/file-like
arguments select the multipart candidate when one is declared.

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
  constraints
- branch-local missing fields are reported as `source=request_body_branch` when
  the caller supplied a discriminator value that selects that branch
- `unused_arguments`: provided arguments that are not part of the tool contract
- `used_arguments`: classified path/query/header/cookie/body argument names
- `selected_content_type`: request body media type selected from OpenAPI metadata

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
