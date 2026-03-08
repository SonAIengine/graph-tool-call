"""Tests for BM25 scorer."""

from __future__ import annotations

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.retrieval.keyword import BM25Scorer


def _make_tool(
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    parameters: list[ToolParameter] | None = None,
) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=description,
        tags=tags or [],
        parameters=parameters or [],
    )


def _build_tools() -> dict[str, ToolSchema]:
    tools = [
        _make_tool("read_file", "Read contents of a file from disk"),
        _make_tool("write_file", "Write contents to a file on disk"),
        _make_tool("delete_file", "Delete a file from the filesystem"),
        _make_tool("query_database", "Execute SQL query on a database"),
        _make_tool("insert_record", "Insert a record into a database table"),
        _make_tool("send_email", "Send an email message"),
    ]
    return {t.name: t for t in tools}


def test_tokenize_camel_case():
    tokens = BM25Scorer._tokenize("getUserById")
    assert tokens == ["get", "user", "by", "id"]


def test_tokenize_snake_case():
    tokens = BM25Scorer._tokenize("list_all_pets")
    # Stemming: "pets" → "pet" (original "pets" also kept)
    assert "list" in tokens
    assert "all" in tokens
    assert "pet" in tokens
    assert "pets" in tokens


def test_tokenize_kebab_case():
    tokens = BM25Scorer._tokenize("send-email")
    assert tokens == ["send", "email"]


def test_bm25_exact_match_highest():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("read file")

    assert "read_file" in scores
    # read_file should have the highest score since it matches the query exactly
    top_tool = max(scores, key=scores.get)  # type: ignore[arg-type]
    assert top_tool == "read_file"


def test_bm25_description_match():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("execute SQL query")

    assert "query_database" in scores
    assert scores["query_database"] > 0


def test_bm25_empty_query():
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    scores = scorer.score("")

    assert scores == {}


def test_bm25_all_tools_scored():
    """Query that matches terms from multiple tools should score them all."""
    tools = _build_tools()
    scorer = BM25Scorer(tools)
    # "file" appears in read_file, write_file, delete_file descriptions/names
    scores = scorer.score("file")

    assert len(scores) >= 3
    for name in ["read_file", "write_file", "delete_file"]:
        assert name in scores
        assert scores[name] > 0


# ---------------------------------------------------------------------------
# Korean bigram tokenization tests
# ---------------------------------------------------------------------------


def test_tokenize_korean_bigrams():
    """_korean_bigrams should produce character-level bigrams from Korean text."""
    bigrams = BM25Scorer._korean_bigrams("정기주문해지")
    assert bigrams == ["정기", "기주", "주문", "문해", "해지"]


def test_korean_query_matches_tool():
    """Korean query should match a tool with Korean description via bigrams."""
    tool = _make_tool(
        "cancelSubscription",
        description="정기주문을 해지하는 API",
    )
    tools = {tool.name: tool}
    scorer = BM25Scorer(tools)
    scores = scorer.score("주문해지")
    assert "cancelSubscription" in scores
    assert scores["cancelSubscription"] > 0


def test_mixed_korean_english():
    """Tokenization of mixed Korean/English text produces both bigrams and English tokens."""
    tokens = BM25Scorer._tokenize("주문order 해지cancel")
    # Should contain the original Korean tokens and their bigrams
    assert "주문order" in tokens  # original token (lowered, no split since no camelCase)
    assert "해지cancel" in tokens
    # Korean bigrams from "주문order" (only Korean chars: 주문 -> one bigram "주문")
    assert "주문" in tokens
    # Korean bigrams from "해지cancel" (only Korean chars: 해지 -> one bigram "해지")
    assert "해지" in tokens
    # English parts from camelCase split — "order" and "cancel" are part of mixed tokens
    # They remain as part of their original tokens since there's no camelCase boundary
