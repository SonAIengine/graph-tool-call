"""LangChain integration."""

__all__ = [
    "GraphToolRetriever",
    "GraphToolkit",
    "filter_tools",
    "langchain_tools_to_schemas",
    "tool_schema_to_openai_function",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "GraphToolRetriever": ("graph_tool_call.langchain.retriever", "GraphToolRetriever"),
    "GraphToolkit": ("graph_tool_call.toolkit", "GraphToolkit"),
    "filter_tools": ("graph_tool_call.toolkit", "filter_tools"),
    "langchain_tools_to_schemas": ("graph_tool_call.langchain.tools", "langchain_tools_to_schemas"),
    "tool_schema_to_openai_function": (
        "graph_tool_call.langchain.tools",
        "tool_schema_to_openai_function",
    ),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call.langchain' has no attribute {name!r}")
