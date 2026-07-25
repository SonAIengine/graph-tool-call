---
title: Installation
description: Install graph-tool-call with the right extras for OpenAPI, Korean search, MCP, embeddings, and local development.
---

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

## Choose Extras

Install only what your integration needs:

```bash
# OpenAPI JSON/YAML ingestion
pip install "graph-tool-call[openapi]"

# Korean query support for mixed Korean/English API catalogs
pip install "graph-tool-call[korean]"

# MCP server and proxy helpers
pip install "graph-tool-call[mcp]"

# Everything used by docs, examples, and optional integrations
pip install "graph-tool-call[all]"
```

For a large OpenAPI API collection, the common install is:

```bash
pip install "graph-tool-call[openapi,korean]"
```

## Verify The Install

```bash
python - <<'PY'
import graph_tool_call
from graph_tool_call import ToolGraph

print(graph_tool_call.__version__)
print(ToolGraph)
PY
```

If the import works, try a local CLI check:

```bash
graph-tool-call --help
```

## Environment Notes

| Environment | Recommendation |
| --- | --- |
| application server | pin an exact package version |
| local engine development | use Poetry and all extras |
| product adapter development | editable install is fine locally, but do not commit editable pins |
| CI docs build | install website dependencies separately under `website/` |

For production adapters, pin the package exactly:

```text
graph-tool-call[korean]==0.32.1
```

Use the version your product has validated. Do not float to the latest release
inside deployment manifests.

For development:

```bash
poetry install --with dev --all-extras
poetry run pytest tests/ -q
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| YAML OpenAPI fails | `openapi` extra missing | install `graph-tool-call[openapi]` |
| Korean query quality is poor | tokenizer extra missing | install `graph-tool-call[korean]` |
| MCP server import fails | MCP SDK extra missing | install `graph-tool-call[mcp]` |
| local embeddings unavailable | embedding extra missing | install `embedding` or `embedding-local` |
| deployed product changed behavior unexpectedly | floating dependency | use an exact version pin |

## Next Step

Continue with [Quickstart](./quickstart.md) to ingest an OpenAPI spec and run a
first retrieval query.
