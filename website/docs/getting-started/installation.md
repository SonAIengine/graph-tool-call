# Installation

The core package is designed to stay small. Optional capabilities are exposed as
extras.

| Extra | Adds | Use When |
| --- | --- | --- |
| `openapi` | YAML parsing | You ingest YAML OpenAPI specs |
| `korean` | Korean tokenizer | You search Korean queries over mixed Korean/English APIs |
| `mcp` | MCP server/proxy support | You expose retrieval through MCP |
| `embedding` | NumPy embedding hooks | You combine graph retrieval with vector similarity |
| `embedding-local` | sentence-transformers | You run local embedding models |
| `similarity` | fuzzy matching | You need duplicate detection |
| `visualization` | graph export dependencies | You export visual graph files |
| `dashboard` | Dash dashboard dependencies | You run the local interactive dashboard |

```bash
pip install graph-tool-call
pip install "graph-tool-call[openapi,korean]"
```

For development:

```bash
poetry install --with dev --all-extras
poetry run pytest tests/ -q
```

