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
