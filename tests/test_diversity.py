"""Tests for MMR diversity reranking."""

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.diversity import mmr_rerank


def _make_tool(name: str, desc: str) -> ToolSchema:
    return ToolSchema(name=name, description=desc)


def test_mmr_empty():
    result = mmr_rerank([], {})
    assert result == []


def test_mmr_single_tool():
    tool = _make_tool("read_file", "Read a file")
    result = mmr_rerank([tool], {"read_file": 1.0})
    assert len(result) == 1
    assert result[0].name == "read_file"


def test_mmr_promotes_diverse_results():
    """Similar tools should be spread apart by MMR."""
    tools = [
        _make_tool("read_file", "Read contents of a file from disk"),
        _make_tool("read_file_v2", "Read contents of a file from disk version 2"),
        _make_tool("send_email", "Send an email message to a recipient"),
        _make_tool("query_db", "Execute SQL query on a database"),
    ]
    scores = {
        "read_file": 1.0,
        "read_file_v2": 0.95,
        "send_email": 0.8,
        "query_db": 0.7,
    }

    # Without MMR: read_file, read_file_v2, send_email, query_db
    # With MMR (lambda=0.5): should push read_file_v2 down
    result = mmr_rerank(tools, scores, lambda_=0.5, top_k=4)
    names = [t.name for t in result]
    assert names[0] == "read_file"  # highest relevance, always first
    # read_file_v2 should not be second due to high similarity with read_file
    assert names[1] != "read_file_v2"


def test_mmr_high_lambda_preserves_relevance_order():
    """With lambda close to 1.0, order should mostly follow relevance."""
    tools = [
        _make_tool("a", "unique tool alpha"),
        _make_tool("b", "unique tool beta"),
        _make_tool("c", "unique tool gamma"),
    ]
    scores = {"a": 1.0, "b": 0.8, "c": 0.5}

    result = mmr_rerank(tools, scores, lambda_=0.99)
    names = [t.name for t in result]
    assert names == ["a", "b", "c"]


def test_mmr_respects_top_k():
    tools = [_make_tool(f"tool_{i}", f"Description {i}") for i in range(5)]
    scores = {f"tool_{i}": 1.0 - i * 0.1 for i in range(5)}

    result = mmr_rerank(tools, scores, top_k=3)
    assert len(result) == 3
