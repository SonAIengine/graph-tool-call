"""Analyze layer: automatic dependency detection and operational reporting."""

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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ConflictResult": ("graph_tool_call.analyze.conflict", "ConflictResult"),
    "detect_conflicts": ("graph_tool_call.analyze.conflict", "detect_conflicts"),
    "DetectedRelation": ("graph_tool_call.analyze.dependency", "DetectedRelation"),
    "detect_dependencies": ("graph_tool_call.analyze.dependency", "detect_dependencies"),
    "CategorySummary": ("graph_tool_call.analyze.report", "CategorySummary"),
    "GraphAnalysisReport": ("graph_tool_call.analyze.report", "GraphAnalysisReport"),
    "analyze_graph": ("graph_tool_call.analyze.report", "analyze_graph"),
    "DuplicatePair": ("graph_tool_call.analyze.similarity", "DuplicatePair"),
    "MergeStrategy": ("graph_tool_call.analyze.similarity", "MergeStrategy"),
    "find_duplicates": ("graph_tool_call.analyze.similarity", "find_duplicates"),
    "merge_duplicates": ("graph_tool_call.analyze.similarity", "merge_duplicates"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call.analyze' has no attribute {name!r}")
