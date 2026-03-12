"""Analyze layer: automatic dependency detection and operational reporting."""

from graph_tool_call.analyze.conflict import ConflictResult, detect_conflicts
from graph_tool_call.analyze.dependency import DetectedRelation, detect_dependencies
from graph_tool_call.analyze.report import CategorySummary, GraphAnalysisReport, analyze_graph
from graph_tool_call.analyze.similarity import (
    DuplicatePair,
    MergeStrategy,
    find_duplicates,
    merge_duplicates,
)

__all__ = [
    "CategorySummary",
    "ConflictResult",
    "DetectedRelation",
    "DuplicatePair",
    "GraphAnalysisReport",
    "MergeStrategy",
    "analyze_graph",
    "detect_conflicts",
    "detect_dependencies",
    "find_duplicates",
    "merge_duplicates",
]
