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

from graph_tool_call.graphify.catalog import (
    build_candidate_set,
    build_tool_equivalence_groups,
    expand_candidates_with_producers,
    select_target_candidate,
    target_action_priority_for_query,
)
from graph_tool_call.graphify.collection_artifact import build_openapi_collection_artifact
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index
from graph_tool_call.graphify.dependency_closure import (
    DEPENDENCY_CLOSURE_POLICY_REVISION,
    TOOL_BUNDLE_POLICY_REVISION,
    DependencyClosureResult,
    ToolBundle,
    assemble_tool_bundle,
    complete_target_dependencies,
    contract_projected_tool_schema,
)
from graph_tool_call.graphify.edges import (
    EVIDENCE_API_CONTRACT,
    EVIDENCE_ARAZZO,
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
from graph_tool_call.graphify.execution_flow import (
    EXECUTION_FLOW_SCHEMA_VERSION,
    classify_execution_edge,
    derive_execution_flow,
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
from graph_tool_call.graphify.io_contract import (
    CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION,
    build_io_contract,
    promote_api_contract_signals,
)
from graph_tool_call.graphify.metadata import (
    COLLECTION_GRAPH_VERSION,
    annotate_graphify_metadata,
    detect_enrichment_status,
)
from graph_tool_call.graphify.retrieval import (
    render_subgraph_text,
    retrieve_graphify,
)
from graph_tool_call.graphify.semantics import (
    annotate_openapi_tool_semantics,
    derive_openapi_tool_semantics,
    summarize_edge_quality,
    summarize_openapi_semantics,
)
from graph_tool_call.graphify.workflow_evidence import (
    apply_arazzo_relations,
    apply_arazzo_workflows,
)

__all__ = [
    "COLLECTION_GRAPH_VERSION",
    "CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION",
    "DEPENDENCY_CLOSURE_POLICY_REVISION",
    "DEFAULT_CONF_AMBIGUOUS",
    "DEFAULT_CONF_EXTRACTED",
    "DEFAULT_CONF_INFERRED",
    "EVIDENCE_ARAZZO",
    "EVIDENCE_API_CONTRACT",
    "EVIDENCE_LLM_CURATED",
    "EVIDENCE_MANUAL",
    "EVIDENCE_NAME_BASED",
    "EVIDENCE_OPENAPI_LINK",
    "EVIDENCE_PROVEN",
    "EVIDENCE_RUN",
    "EVIDENCE_STRUCTURAL",
    "EXECUTION_FLOW_SCHEMA_VERSION",
    "TOOL_BUNDLE_POLICY_REVISION",
    "DependencyClosureResult",
    "ToolBundle",
    "_apply_pair_hints",
    "annotate_graphify_metadata",
    "annotate_openapi_tool_semantics",
    "apply_arazzo_relations",
    "apply_arazzo_workflows",
    "assemble_tool_bundle",
    "bucket_confidence",
    "build_candidate_set",
    "build_openapi_collection_artifact",
    "build_io_contract",
    "build_tool_equivalence_groups",
    "complete_target_dependencies",
    "classify_execution_edge",
    "contract_projected_tool_schema",
    "derive_plan_trace_edges",
    "derive_execution_flow",
    "derive_openapi_tool_semantics",
    "detect_enrichment_status",
    "expand_candidates_with_producers",
    "extract_openapi_contract_index",
    "ingest_openapi_graphify",
    "merge_graph_edges",
    "normalize_graph_edge",
    "preserve_refs_for_detection",
    "promote_api_contract_signals",
    "render_subgraph_text",
    "retrieve_graphify",
    "select_target_candidate",
    "summarize_edge_quality",
    "summarize_openapi_semantics",
    "target_action_priority_for_query",
]
