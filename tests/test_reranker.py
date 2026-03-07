"""Tests for cross-encoder reranker."""

from unittest.mock import MagicMock

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.reranker import CrossEncoderReranker


def _make_tool(name: str, desc: str) -> ToolSchema:
    return ToolSchema(name=name, description=desc)


def test_rerank_empty():
    reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
    reranker._model_name = "test"
    reranker._model = None
    result = reranker.rerank("query", [])
    assert result == []


def test_rerank_orders_by_score():
    reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
    mock_model = MagicMock()
    # Higher score for tool_b
    mock_model.predict.return_value = [0.3, 0.9, 0.1]
    reranker._model = mock_model

    tools = [
        _make_tool("tool_a", "low relevance"),
        _make_tool("tool_b", "high relevance"),
        _make_tool("tool_c", "lowest relevance"),
    ]

    result = reranker.rerank("test query", tools)
    assert [t.name for t in result] == ["tool_b", "tool_a", "tool_c"]


def test_rerank_respects_top_k():
    reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.9, 0.5, 0.1]
    reranker._model = mock_model

    tools = [
        _make_tool("a", "desc a"),
        _make_tool("b", "desc b"),
        _make_tool("c", "desc c"),
    ]

    result = reranker.rerank("query", tools, top_k=2)
    assert len(result) == 2
    assert result[0].name == "a"


def test_tool_text_includes_all_fields():
    reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
    tool = ToolSchema(
        name="send_email",
        description="Send an email message",
        tags=["communication"],
    )
    text = reranker._tool_text(tool)
    assert "send_email" in text
    assert "Send an email" in text
    assert "communication" in text
