"""Analyze layer: automatic dependency detection and deduplication."""

from graph_tool_call.analyze.dependency import DetectedRelation, detect_dependencies
from graph_tool_call.analyze.similarity import (
    DuplicatePair,
    MergeStrategy,
    find_duplicates,
    merge_duplicates,
)

__all__ = [
    "DetectedRelation",
    "DuplicatePair",
    "MergeStrategy",
    "detect_dependencies",
    "find_duplicates",
    "merge_duplicates",
]
