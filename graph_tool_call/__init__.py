"""graph-tool-call: Graph-structured tool retrieval for LLM agents."""

from graph_tool_call.analyze.similarity import DuplicatePair, MergeStrategy
from graph_tool_call.core.tool import MCPAnnotations, ToolSchema, normalize_tool, parse_tool
from graph_tool_call.ontology.schema import NodeType, RelationType
from graph_tool_call.retrieval.engine import RetrievalResult, SearchMode
from graph_tool_call.tool_graph import ToolGraph

__all__ = [
    "DuplicatePair",
    "MCPAnnotations",
    "MergeStrategy",
    "NodeType",
    "normalize_tool",
    "RelationType",
    "RetrievalResult",
    "SearchMode",
    "ToolGraph",
    "ToolSchema",
    "parse_tool",
]

__version__ = "0.7.1"
