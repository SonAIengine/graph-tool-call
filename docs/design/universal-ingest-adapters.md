# Universal Ingest Adapters

## Goal

`graph-tool-call` must accept future API and tool description formats without
adding source-specific branches to retrieval, graph construction, planning, or
XGEN product code.

The library cannot predict every future protocol. It can guarantee a stable
extension boundary:

```text
source document or catalog
  -> IngestAdapter
  -> IngestResult
  -> ToolSchema[]
  -> graph, retrieval, selector, plan, runner
```

## Canonical contract

Every adapter returns `IngestResult`:

| Field | Purpose |
|---|---|
| `tools` | Canonical `ToolSchema` objects |
| `adapter` | Stable adapter identifier |
| `capabilities` | Features and transports the adapter can preserve |
| `issues` | Stable blocker/warning diagnostics |
| `metadata` | Source-level provenance that is safe to persist |

Each emitted tool receives additive `metadata.ingest` provenance with the
adapter, source type, and declared capabilities. Existing OpenAPI, MCP, and
function metadata remains unchanged.

Capability names are open strings rather than a closed enum. New protocol
features can therefore be declared without releasing a new core enum first.
Initial names include:

- `input_schema`
- `output_schema`
- `authentication`
- `annotations`
- `operation_links`
- `streaming`
- `vendor_extensions`
- `local_execution`
- `server_provenance`

## Detection policy

Auto-detection is appropriate only when evidence is strong:

- OpenAPI/Swagger version keys
- MCP `inputSchema` tool rows
- Python callables
- recognizable generic function-tool dictionaries

An arbitrary `.json` URL is not enough evidence. The caller should supply
`format_hint` for ambiguous paths or URLs. If two adapters have effectively the
same confidence, ingest fails with `AmbiguousIngestAdapterError` instead of
choosing one silently.

## Conformance policy

The registry adds deterministic issues after conversion:

| Code | Severity | Meaning |
|---|---|---|
| `empty_tool_catalog` | blocker | No tools were produced |
| `invalid_tool_schema` | blocker | Adapter output is not a `ToolSchema` |
| `invalid_tool_name` | blocker | Canonical tool name is empty |
| `duplicate_tool_name` | blocker | Canonical names are not unique |
| `unsupported_capability` | blocker | A caller-required feature cannot be guaranteed |
| `incomplete_required_capability` | blocker | A required feature is present for only part of the catalog |
| `missing_tool_description` | warning | Semantic retrieval evidence is weak |

`strict=False` returns diagnostics for UI/readiness workflows.
`strict=True` raises `IngestConformanceError` when any blocker exists.

Unsupported protocol facts must not be discarded and reported as ready.
Adapters should either preserve them in `ToolSchema.metadata`, declare a
limitation, or emit a stable issue.

Adapter selection raises stable exceptions:

| Exception | Meaning |
|---|---|
| `UnknownIngestAdapterError` | No confident match, or an unknown `format_hint` |
| `AmbiguousIngestAdapterError` | Multiple adapters have equivalent strong evidence |
| `IngestConformanceError` | `strict=True` and one or more blocker issues exist |

## Adding a new source

An adapter implements:

```python
class IngestAdapter(Protocol):
    name: str
    capabilities: IngestCapabilities

    def detect(self, source: Any) -> float: ...
    def ingest(self, source: Any, **options: Any) -> IngestResult: ...
```

Registration can be process-local:

```python
registry = IngestAdapterRegistry()
registry.register(MyAdapter())
result = registry.ingest(source)
```

or application-wide:

```python
register_ingest_adapter(MyAdapter())
result = ingest_source(source)
```

An adapter conformance suite should cover:

1. strong and weak source detection
2. canonical unique tool names
3. request and response schema preservation
4. auth/security facts without credential values
5. execution transport provenance
6. unsupported feature diagnostics
7. stable serialization through `IngestResult.to_dict()`

## XGEN boundary

XGEN may choose adapters, store source documents, resolve credentials, display
issues, and execute tools. It should not contain protocol parsing that is
product-neutral.

Source-specific dictionaries for one customer or domain remain XGEN adapter
configuration. They do not belong in the core registry.

## Built-in GraphQL introspection adapter

Standard GraphQL introspection responses are recognized as
`graphql-introspection`. Each query, mutation, and subscription root field
becomes a stable `ToolSchema`. The adapter preserves:

- GraphQL argument and result types as JSON Schema
- a variable-based operation document
- operation type, root type, root field, and deprecation facts
- a transport-neutral execution descriptor in `metadata.execution`
- `api_contract.produces/consumes` rows for graph build and planning
- a deterministic schema fingerprint without persisting the source response

The GraphQL specification does not include the service URL in introspection,
so `endpoint_url` is required for an execution-ready result. It must not include
userinfo credentials or sensitive query parameters. Credentials remain in the
application auth layer.

Subscription fields are retained for discovery, but a warning records that an
application-provided WebSocket/SSE transport is required. See
[GraphQL Introspection Ingest](graphql-introspection-ingest.md).

## Built-in MCP catalog adapter

`mcp-tools` accepts bare rows, `{tools: [...]}`, and JSON-RPC
`{result: {tools: [...]}}` pages. It preserves:

- display `title` and annotation title precedence
- complete `inputSchema` and optional `outputSchema`
- behavioral annotations with an explicit untrusted provenance flag
- `execution.taskSupport` as metadata
- server name/version and protocol version when supplied
- input/output-derived `api_contract` evidence

Duplicate names and invalid input schemas are diagnosed deterministically.
An unconsumed `nextCursor` blocks readiness by default, and catalog/tool limits
prevent silent unbounded ingestion.

This adapter describes tools; it does not execute them. Products must bind the
catalog to an authenticated MCP session and provide the protocol transport.

## Follow-up adapters

The extension boundary enables independent work in this order:

1. gRPC/protobuf service descriptors
2. AsyncAPI channels and messages
3. Postman collections and HAR traces
4. proprietary RPC catalogs

Each adapter must pass the same conformance contract before it is advertised as
supported. A new adapter does not require changes to graph search, target
selection, planning, or runner event schemas.
