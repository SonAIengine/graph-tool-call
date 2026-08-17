<div align="center">

# graph-tool-call

**Graph-structured retrieval for large LLM tool catalogs.**

Find the target tool, the prerequisite tools that produce its inputs, and the
smallest schema bundle that fits the planner's token budget.

[Documentation](https://sonaiengine.github.io/graph-tool-call/) ·
[Quickstart](https://sonaiengine.github.io/graph-tool-call/docs/getting-started/quickstart) ·
[PyPI](https://pypi.org/project/graph-tool-call/) ·
[Benchmarks](docs/benchmarks.md)

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Core dependencies](https://img.shields.io/badge/core_dependencies-0-brightgreen.svg)](#installation)

English · [한국어](README-ko.md)

</div>

---

## The Problem

A semantic search for "refund an order" can find `refundOrder`. That is not
enough when the operation requires an `order_id` that the user does not have.
A usable candidate set also needs the operation that produces that field:

```text
findOrdersByEmail(email) -> order_id -> refundOrder(order_id)
```

Large catalogs create a second problem: sending every schema to the model wastes
context and can lower selection quality. graph-tool-call treats retrieval as a
contract-aware graph problem instead of flat similarity search.

It provides:

- deterministic ingestion from OpenAPI, GraphQL introspection, MCP tools,
  Python functions, and structured tool catalogs;
- hybrid target retrieval with keyword, graph, optional embedding, and MCP
  annotation signals;
- evidence-backed target selection and typed prerequisite expansion;
- token-budgeted, contract-projected schemas for the model-facing catalog;
- readiness, failure, and trace metadata for application-side diagnostics;
- adapters for OpenAI, Anthropic, LangChain v1, MCP, Docker, and Kubernetes.

Authentication, tenant policy, approval, and product-specific execution remain
in the host application.

## See It in 30 Seconds

No model, API key, or network call is required:

```bash
uvx graph-tool-call demo dependency-chain
```

```text
Selected target:
  refundOrder(order_id)

Required producer:
  findOrdersByEmail(email) -> order_id
  evidence: api_contract, openapi_link

Execution order:
  1. findOrdersByEmail
  2. refundOrder

Planner context:
  6 catalog tools -> 2 required tools
  estimated tokens: 1476 -> 160 (89% fewer)
```

This demo runs the real retriever, deterministic target selector, typed
dependency closure, and schema admission pipeline.

## Installation

The core search and graph package uses only the Python standard library.
Optional integrations are installed explicitly:

```bash
pip install graph-tool-call
pip install "graph-tool-call[openapi]"       # YAML OpenAPI documents
pip install "graph-tool-call[korean]"        # Kiwi tokenizer
pip install "graph-tool-call[langchain]"     # LangChain v1 middleware
pip install "graph-tool-call[mcp]"           # MCP server and proxy
pip install "graph-tool-call[all]"           # all optional features
```

Python 3.10 through 3.14 are tested in CI.

## Build and Search

### OpenAPI

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.graph.json",
)

for result in graph.retrieve_with_scores("create a new pet", top_k=5):
    print(result.tool.name, result.score, result.confidence)
```

OpenAPI ingestion preserves request and response schemas, parameter locations,
content types, security requirements, links, examples, response envelopes, and
typed `consumes`/`produces` contracts. Swagger 2.0, OpenAPI 3.0, and OpenAPI 3.1
are supported.

Inspect a collection before exposing it to an agent:

```bash
graph-tool-call inspect-openapi ./openapi.json --json
graph-tool-call build-openapi-collection ./openapi.json -o collection.json
```

The report contains stable readiness issue codes, semantic coverage, and edge
quality rather than a single opaque score.

### Other sources

```python
from graph_tool_call.ingest import ingest_source

openapi_result = ingest_source(openapi_document)
graphql_result = ingest_source(introspection_result)
mcp_result = ingest_source({"tools": mcp_tools}, format_hint="mcp-tools")
python_result = ingest_source([read_file, write_file])
```

Every adapter returns normalized `ToolSchema` objects, capability metadata, and
structured unsupported-feature diagnostics.

## Choose an Integration

| Environment | Recommended surface | What graph-tool-call owns |
| --- | --- | --- |
| Python application | `ToolGraph` / graphify APIs | ingest, search, evidence, dependency closure |
| OpenAI Responses or Chat Completions | `patch_openai` | per-request function-tool filtering |
| Anthropic Messages | `patch_anthropic` | per-request tool filtering |
| LangChain v1 | `create_tool_selection_middleware` | model-call tool selection |
| Claude Code, Cursor, Windsurf | MCP proxy | many MCP backends behind 3 gateway tools |
| OpenAI Agents, PydanticAI, Google ADK | remote MCP server | protocol-neutral search service |
| Docker or Kubernetes | Streamable HTTP MCP | private deployable service |

See the [compatibility matrix](https://sonaiengine.github.io/graph-tool-call/docs/integrations/ecosystem-compatibility)
for validation boundaries. Protocol compatibility does not imply that every
framework or cloud release is tested by this repository.

### OpenAI Responses

```python
from graph_tool_call.middleware import patch_openai

patch_openai(client, graph=graph, top_k=5)

response = client.responses.create(
    model=model_name,
    input="delete a user account",
    tools=all_function_tools,
)
```

Hosted tools such as web search pass through unchanged. The same patch keeps
legacy Chat Completions support.

### LangChain v1

```python
from langchain.agents import create_agent
from graph_tool_call.langchain import create_tool_selection_middleware

selection = create_tool_selection_middleware(langchain_tools, top_k=5)
agent = create_agent(
    model,
    tools=langchain_tools,
    middleware=[selection],
)
```

The middleware intersects with tools still allowed by earlier permission or
feature-flag middleware; it does not reintroduce filtered tools.

### MCP server

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

The MCP endpoint is `/mcp`; HTTP deployments also expose `/healthz` and
`/readyz`. Keep remote endpoints private or behind an authenticated gateway.

### MCP proxy

```bash
graph-tool-call proxy \
  --config ./mcp-backends.json \
  --transport streamable-http
```

The proxy accepts local stdio, SSE, and Streamable HTTP backends. In gateway
mode it exposes `search_tools`, `get_tool_schema`, and `call_backend_tool`, then
notifies capable clients when matching backend tools become visible.

## Reproducible Evidence

The release headline is deliberately model-free and small enough to replay in
CI. On seven curated commerce cases, adding typed producer expansion to the same
selected target produced:

| Metric | Target only | Target + graph producers |
| --- | ---: | ---: |
| Required-producer recall | 14.3% | **100%** |
| Candidate plan coverage | 47.6% | **100%** |
| Candidate binding support | 14.3% | **100%** |
| Target Recall@5 | - | **100%** |

The [case-level v0.45.0 artifact](benchmarks/results/releases/v0.45.0/dependency-chain-evidence.json)
records fixture hashes, every expected target and producer, and replay commands:

```bash
make launch-evidence
make launch-evidence-check
```

The separate
[observability artifact](benchmarks/results/releases/v0.45.0/observability-evidence.json)
checks that tracing leaves engine inputs unchanged, replays deterministically,
scrubs secrets, explains every decision, and stays below the documented
`5ms/span` p95 capture-cost gate:

```bash
make observability-evidence-check
```

This is an engine regression suite, not a population-level estimate of LLM
tool-calling accuracy and not a state-of-the-art claim. Larger external
comparisons, model-loop experiments, confidence intervals, and known weak cases
are reported in [Benchmark Results](docs/benchmarks.md) and the
[paper protocol](docs/research/paper-readiness-design.md).

## Production Boundary

graph-tool-call is the retrieval and contract layer. A production adapter still
owns:

- user and service authentication;
- tenant authorization and approval policy;
- downstream secrets and cookie handling;
- side-effect confirmation, cleanup, and audit retention;
- provider/model lifecycle and final response policy.

Do not store raw credentials in graph artifacts, tool descriptions, trace
records, or model-visible arguments.

## Documentation

| Start here | Purpose |
| --- | --- |
| [Quickstart](https://sonaiengine.github.io/graph-tool-call/docs/getting-started/quickstart) | first search, graph, readiness, and execution loop |
| [Mental model](https://sonaiengine.github.io/graph-tool-call/docs/getting-started/mental-model) | understand the pipeline and boundaries |
| [OpenAPI ingestion](https://sonaiengine.github.io/graph-tool-call/docs/build/openapi-ingestion) | contract extraction and collection build |
| [Target selection](https://sonaiengine.github.io/graph-tool-call/docs/search/target-selection) | ranking evidence and deterministic guard |
| [Integrations](https://sonaiengine.github.io/graph-tool-call/docs/integrations/ecosystem-compatibility) | frameworks, MCP, and deployment |
| [API reference](https://sonaiengine.github.io/graph-tool-call/docs/reference/public-api) | stable public Python surface |
| [Roadmap](docs/roadmap.md) | current product and research priorities |

## Development

```bash
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
poetry install --with dev --all-extras

poetry run ruff check .
poetry run ruff format --check .
poetry run pytest tests/ -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[release checklist](docs/release-checklist.md).

## License

[MIT](LICENSE)
