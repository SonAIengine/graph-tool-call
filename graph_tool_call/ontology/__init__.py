"""Ontology construction: builder, LLM provider, schema."""

from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import NodeType, RelationType

__all__ = [
    "InferredRelation",
    "NodeType",
    "OllamaOntologyLLM",
    "OntologyBuilder",
    "OntologyLLM",
    "OpenAICompatibleOntologyLLM",
    "RelationType",
    "ToolSummary",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "InferredRelation": ("graph_tool_call.ontology.llm_provider", "InferredRelation"),
    "OllamaOntologyLLM": ("graph_tool_call.ontology.llm_provider", "OllamaOntologyLLM"),
    "OntologyLLM": ("graph_tool_call.ontology.llm_provider", "OntologyLLM"),
    "OpenAICompatibleOntologyLLM": (
        "graph_tool_call.ontology.llm_provider",
        "OpenAICompatibleOntologyLLM",
    ),
    "ToolSummary": ("graph_tool_call.ontology.llm_provider", "ToolSummary"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'graph_tool_call.ontology' has no attribute {name!r}")
