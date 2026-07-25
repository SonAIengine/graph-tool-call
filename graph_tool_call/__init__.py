"""graph-tool-call: Graph-structured tool retrieval for LLM agents."""

from graph_tool_call.core.tool import MCPAnnotations, ToolSchema, normalize_tool, parse_tool
from graph_tool_call.ontology.schema import NodeType, RelationType
from graph_tool_call.tool_graph import ToolGraph

__all__ = [
    "CategorySummary",
    "CompressConfig",
    "DuplicatePair",
    "GraphAnalysisReport",
    "GraphToolkit",
    "AmbiguousIngestAdapterError",
    "IngestAdapter",
    "IngestAdapterError",
    "IngestAdapterRegistry",
    "IngestCapabilities",
    "IngestConformanceError",
    "GraphQLIntrospectionIngestAdapter",
    "IngestIssue",
    "IngestResult",
    "UnknownIngestAdapterError",
    "apply_learning_suggestions",
    "build_trace_learning_record",
    "compress_tool_result",
    "create_gateway_tools",
    "derive_learning_suggestions",
    "MCPAnnotations",
    "MergeStrategy",
    "NodeType",
    "normalize_tool",
    "RelationType",
    "RetrievalResult",
    "SearchMode",
    "ToolCallAssessment",
    "ToolCallDecision",
    "ToolCallPolicy",
    "ToolGraph",
    "ToolSchema",
    "filter_tools",
    "detect_ingest_adapter",
    "get_default_ingest_registry",
    "ingest_source",
    "ingest_graphql_introspection",
    "is_graphql_introspection",
    "parse_tool",
    "register_ingest_adapter",
    "scrub_trace_payload",
    "unregister_ingest_adapter",
]

__version__ = "0.33.0"

# Lazy imports for analyze/assist symbols — avoid loading heavy submodules at import time
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "CategorySummary": ("graph_tool_call.analyze.report", "CategorySummary"),
    "GraphAnalysisReport": ("graph_tool_call.analyze.report", "GraphAnalysisReport"),
    "DuplicatePair": ("graph_tool_call.analyze.similarity", "DuplicatePair"),
    "MergeStrategy": ("graph_tool_call.analyze.similarity", "MergeStrategy"),
    "ToolCallAssessment": ("graph_tool_call.assist.policy", "ToolCallAssessment"),
    "ToolCallDecision": ("graph_tool_call.assist.policy", "ToolCallDecision"),
    "ToolCallPolicy": ("graph_tool_call.assist.policy", "ToolCallPolicy"),
    "RetrievalResult": ("graph_tool_call.retrieval.engine", "RetrievalResult"),
    "SearchMode": ("graph_tool_call.retrieval.engine", "SearchMode"),
    "create_gateway_tools": ("graph_tool_call.langchain.gateway", "create_gateway_tools"),
    "filter_tools": ("graph_tool_call.toolkit", "filter_tools"),
    "GraphToolkit": ("graph_tool_call.toolkit", "GraphToolkit"),
    "AmbiguousIngestAdapterError": (
        "graph_tool_call.ingest",
        "AmbiguousIngestAdapterError",
    ),
    "IngestAdapter": ("graph_tool_call.ingest", "IngestAdapter"),
    "IngestAdapterError": ("graph_tool_call.ingest", "IngestAdapterError"),
    "IngestAdapterRegistry": ("graph_tool_call.ingest", "IngestAdapterRegistry"),
    "IngestCapabilities": ("graph_tool_call.ingest", "IngestCapabilities"),
    "IngestConformanceError": ("graph_tool_call.ingest", "IngestConformanceError"),
    "GraphQLIntrospectionIngestAdapter": (
        "graph_tool_call.ingest",
        "GraphQLIntrospectionIngestAdapter",
    ),
    "IngestIssue": ("graph_tool_call.ingest", "IngestIssue"),
    "IngestResult": ("graph_tool_call.ingest", "IngestResult"),
    "UnknownIngestAdapterError": ("graph_tool_call.ingest", "UnknownIngestAdapterError"),
    "detect_ingest_adapter": ("graph_tool_call.ingest", "detect_ingest_adapter"),
    "get_default_ingest_registry": ("graph_tool_call.ingest", "get_default_ingest_registry"),
    "ingest_source": ("graph_tool_call.ingest", "ingest_source"),
    "ingest_graphql_introspection": (
        "graph_tool_call.ingest",
        "ingest_graphql_introspection",
    ),
    "is_graphql_introspection": (
        "graph_tool_call.ingest",
        "is_graphql_introspection",
    ),
    "register_ingest_adapter": ("graph_tool_call.ingest", "register_ingest_adapter"),
    "unregister_ingest_adapter": ("graph_tool_call.ingest", "unregister_ingest_adapter"),
    "compress_tool_result": ("graph_tool_call.compressor", "compress_tool_result"),
    "CompressConfig": ("graph_tool_call.compressor", "CompressConfig"),
    "apply_learning_suggestions": ("graph_tool_call.learning", "apply_learning_suggestions"),
    "build_trace_learning_record": ("graph_tool_call.learning", "build_trace_learning_record"),
    "derive_learning_suggestions": ("graph_tool_call.learning", "derive_learning_suggestions"),
    "scrub_trace_payload": ("graph_tool_call.learning", "scrub_trace_payload"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call' has no attribute {name!r}")
