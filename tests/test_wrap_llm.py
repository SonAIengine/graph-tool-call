"""Tests for LLM auto-wrapping."""

from __future__ import annotations

import json

import pytest

from graph_tool_call.ontology.llm_provider import (
    CallableOntologyLLM,
    OllamaOntologyLLM,
    OntologyLLM,
    OpenAIClientOntologyLLM,
    OpenAICompatibleOntologyLLM,
    wrap_llm,
)


class _MockOntologyLLM(OntologyLLM):
    def generate(self, prompt: str) -> str:
        return "{}"


def test_wrap_ontology_llm_passthrough():
    """OntologyLLM instances should be returned as-is."""
    llm = _MockOntologyLLM()
    assert wrap_llm(llm) is llm


def test_wrap_callable():
    """Callable (str)->str should be wrapped."""
    fn = lambda p: "hello"  # noqa: E731
    wrapped = wrap_llm(fn)
    assert isinstance(wrapped, CallableOntologyLLM)
    assert wrapped.generate("test") == "hello"


def test_wrap_callable_non_string_return():
    """Callable returning non-string should be converted."""
    fn = lambda p: 42  # noqa: E731
    wrapped = wrap_llm(fn)
    assert wrapped.generate("test") == "42"


def test_wrap_string_ollama():
    """'ollama/model' should create OllamaOntologyLLM."""
    wrapped = wrap_llm("ollama/qwen2.5:7b")
    assert isinstance(wrapped, OllamaOntologyLLM)
    assert wrapped.model == "qwen2.5:7b"


def test_wrap_string_openai():
    """'openai/model' should create OpenAICompatibleOntologyLLM."""
    wrapped = wrap_llm("openai/gpt-4o-mini")
    assert isinstance(wrapped, OpenAICompatibleOntologyLLM)
    assert wrapped.model == "gpt-4o-mini"


def test_wrap_string_no_slash_raises():
    """String without '/' should raise ValueError."""
    with pytest.raises(ValueError, match="provider/model"):
        wrap_llm("just-a-model")


def test_wrap_openai_client():
    """Object with chat.completions should be wrapped as OpenAI client."""

    class MockCompletions:
        def create(self, **kwargs):
            class Choice:
                class Message:
                    content = "test response"

                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class MockChat:
        completions = MockCompletions()

    class MockClient:
        chat = MockChat()

    wrapped = wrap_llm(MockClient())
    assert isinstance(wrapped, OpenAIClientOntologyLLM)
    assert wrapped.generate("test") == "test response"


def test_wrap_invalid_type_raises():
    """Non-callable, non-string, non-client should raise TypeError."""
    with pytest.raises(TypeError, match="Cannot auto-wrap"):
        wrap_llm(42)


def test_build_ontology_with_callable():
    """ToolGraph.build_ontology() should accept a callable LLM."""
    from graph_tool_call.tool_graph import ToolGraph

    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "create_order", "description": "Create an order"},
            {"name": "get_order", "description": "Get order by ID"},
        ]
    )

    def mock_llm(prompt: str) -> str:
        if "keyword" in prompt.lower():
            return json.dumps(
                {
                    "create_order": ["order", "create", "new"],
                    "get_order": ["order", "fetch", "retrieve"],
                }
            )
        if "categor" in prompt.lower():
            return json.dumps({"categories": {"orders": ["create_order", "get_order"]}})
        return "[]"

    tg.build_ontology(llm=mock_llm)

    # Keywords should be enriched
    attrs = tg.graph.get_node_attrs("create_order")
    tags = attrs.get("tags", [])
    assert any(k in tags for k in ["order", "create", "new"])
