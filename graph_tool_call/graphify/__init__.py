"""graphify-mode: deterministic edge extraction + zero-vector retrieval.

Inspired by the graphify project (https://github.com/safishamsi/graphify).
The core idea: every edge carries a Confidence label, retrieval is a
keyword-seeded BFS over confidence-weighted edges, and the result is a
token-budgeted text rendering of the matched subgraph — no embeddings,
no wRRF fusion, no MMR reranking.

Public API:
  - ingest_openapi_graphify(schemas) -> (ToolGraph, edge_stats)
  - retrieve_graphify(tg, query, ...) -> {results, subgraph_text, intent, stats}
  - render_subgraph_text(tg, nodes, edges, budget) -> str
"""

from graph_tool_call.graphify.ingest import (
    DEFAULT_CONF_AMBIGUOUS,
    DEFAULT_CONF_EXTRACTED,
    DEFAULT_CONF_INFERRED,
    _apply_pair_hints,
    bucket_confidence,
    ingest_openapi_graphify,
    preserve_refs_for_detection,
)
from graph_tool_call.graphify.retrieval import (
    render_subgraph_text,
    retrieve_graphify,
)

__all__ = [
    "DEFAULT_CONF_AMBIGUOUS",
    "DEFAULT_CONF_EXTRACTED",
    "DEFAULT_CONF_INFERRED",
    "bucket_confidence",
    "ingest_openapi_graphify",
    "preserve_refs_for_detection",
    "render_subgraph_text",
    "retrieve_graphify",
]
