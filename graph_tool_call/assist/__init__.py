"""Assist module: tool call validation, execution policy, and next-step suggestion."""

__all__ = [
    "ToolCallAssessment",
    "ToolCallDecision",
    "ToolCallPolicy",
    "ValidationResult",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ToolCallAssessment": ("graph_tool_call.assist.policy", "ToolCallAssessment"),
    "ToolCallDecision": ("graph_tool_call.assist.policy", "ToolCallDecision"),
    "ToolCallPolicy": ("graph_tool_call.assist.policy", "ToolCallPolicy"),
    "ValidationResult": ("graph_tool_call.assist.validator", "ValidationResult"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call.assist' has no attribute {name!r}")
