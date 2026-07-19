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

from graph_tool_call.graphify.catalog import expand_candidates_with_producers
from graph_tool_call.graphify.edges import (
    EVIDENCE_API_CONTRACT,
    EVIDENCE_LLM_CURATED,
    EVIDENCE_MANUAL,
    EVIDENCE_NAME_BASED,
    EVIDENCE_OPENAPI_LINK,
    EVIDENCE_PROVEN,
    EVIDENCE_RUN,
    EVIDENCE_STRUCTURAL,
    derive_plan_trace_edges,
    merge_graph_edges,
    normalize_graph_edge,
)
from graph_tool_call.graphify.ingest import (
    DEFAULT_CONF_AMBIGUOUS,
    DEFAULT_CONF_EXTRACTED,
    DEFAULT_CONF_INFERRED,
    _apply_pair_hints,
    bucket_confidence,
    ingest_openapi_graphify,
    preserve_refs_for_detection,
)
from graph_tool_call.graphify.io_contract import build_io_contract, promote_api_contract_signals
from graph_tool_call.graphify.metadata import (
    COLLECTION_GRAPH_VERSION,
    annotate_graphify_metadata,
    detect_enrichment_status,
)
from graph_tool_call.graphify.retrieval import (
    render_subgraph_text,
    retrieve_graphify,
)

__all__ = [
    "COLLECTION_GRAPH_VERSION",
    "DEFAULT_CONF_AMBIGUOUS",
    "DEFAULT_CONF_EXTRACTED",
    "DEFAULT_CONF_INFERRED",
    "EVIDENCE_API_CONTRACT",
    "EVIDENCE_LLM_CURATED",
    "EVIDENCE_MANUAL",
    "EVIDENCE_NAME_BASED",
    "EVIDENCE_OPENAPI_LINK",
    "EVIDENCE_PROVEN",
    "EVIDENCE_RUN",
    "EVIDENCE_STRUCTURAL",
    "_apply_pair_hints",
    "annotate_graphify_metadata",
    "bucket_confidence",
    "build_io_contract",
    "derive_plan_trace_edges",
    "detect_enrichment_status",
    "expand_candidates_with_producers",
    "ingest_openapi_graphify",
    "merge_graph_edges",
    "normalize_graph_edge",
    "preserve_refs_for_detection",
    "promote_api_contract_signals",
    "render_subgraph_text",
    "retrieve_graphify",
]
