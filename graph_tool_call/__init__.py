"""graph-tool-call: Graph-structured tool retrieval for LLM agents."""

from graph_tool_call.core.tool import MCPAnnotations, ToolSchema, normalize_tool, parse_tool
from graph_tool_call.ontology.schema import NodeType, RelationType
from graph_tool_call.tool_graph import ToolGraph

__all__ = [
    "CategorySummary",
    "DuplicatePair",
    "GraphAnalysisReport",
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
    "parse_tool",
]

__version__ = "0.11.0"

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
