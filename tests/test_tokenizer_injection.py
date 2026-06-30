"""Tests for the pluggable BM25 tokenizer hook.

Covers wrap_tokenizer auto-detection, BM25Scorer injection, ToolGraph
propagation (including engine-invalidation survival and graphify seed sharing),
and the optional Kiwi morphological tokenizer.
"""

from __future__ import annotations

import pytest

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.keyword import BM25Scorer
from graph_tool_call.retrieval.tokenizer import KiwiTokenizer, wrap_tokenizer
from graph_tool_call.tool_graph import ToolGraph


def _tool(name: str, description: str = "") -> ToolSchema:
    return ToolSchema(name=name, description=description, tags=[], parameters=[])


def _tools() -> dict[str, ToolSchema]:
    items = [
        _tool("trackShipment", "주문 배송상태를 조회하는 API"),
        _tool("cancelOrder", "주문을 취소하는 API"),
        _tool("getProduct", "상품 정보를 조회하는 API"),
    ]
    return {t.name: t for t in items}


def _whitespace_tokenize(text: str) -> list[str]:
    """A real (non-mock) tokenizer: lowercase + whitespace split, no camelCase."""
    return text.lower().split()


# --- wrap_tokenizer auto-detection ---


def test_wrap_tokenizer_none_returns_none():
    assert wrap_tokenizer(None) is None


def test_wrap_tokenizer_callable_passthrough():
    assert wrap_tokenizer(_whitespace_tokenize) is _whitespace_tokenize


def test_wrap_tokenizer_unknown_string_raises():
    with pytest.raises(TypeError):
        wrap_tokenizer("mecab")


def test_wrap_tokenizer_non_callable_raises():
    with pytest.raises(TypeError):
        wrap_tokenizer(123)


# --- BM25Scorer injection ---


def test_bm25_default_is_builtin_tokenizer():
    scorer = BM25Scorer(_tools())
    assert scorer._tokenize_fn is BM25Scorer._tokenize


def test_bm25_default_none_byte_identical():
    tools = _tools()
    a = BM25Scorer(tools)
    b = BM25Scorer(tools, tokenizer=None)
    assert a.score("배송 상태 조회") == b.score("배송 상태 조회")


def test_bm25_custom_tokenizer_used_for_indexing():
    tools = {"x": _tool("FooBar", "hello world")}
    scorer = BM25Scorer(tools, tokenizer=_whitespace_tokenize)
    toks = scorer._tool_tokens["x"]
    # whitespace tokenizer keeps "foobar" whole; the default would camelCase-split to foo/bar
    assert "foobar" in toks
    assert "foo" not in toks


# --- ToolGraph propagation ---


def test_toolgraph_set_tokenizer_propagates_to_bm25():
    tg = ToolGraph()
    for t in _tools().values():
        tg.add_tool(t)
    tg.set_tokenizer(_whitespace_tokenize)
    bm25 = tg._get_retrieval_engine()._get_bm25()
    assert bm25._tokenize_fn is _whitespace_tokenize


def test_set_tokenizer_survives_engine_invalidation():
    tg = ToolGraph()
    for t in _tools().values():
        tg.add_tool(t)
    tg.set_tokenizer(_whitespace_tokenize)
    _ = tg._get_retrieval_engine()._get_bm25()  # build engine once
    tg.add_tool(_tool("newTool", "새로운 도구"))  # invalidates the retrieval engine
    bm25 = tg._get_retrieval_engine()._get_bm25()
    assert bm25._tokenize_fn is _whitespace_tokenize


def test_set_tokenizer_none_restores_builtin():
    tg = ToolGraph()
    for t in _tools().values():
        tg.add_tool(t)
    tg.set_tokenizer(_whitespace_tokenize)
    tg.set_tokenizer(None)
    bm25 = tg._get_retrieval_engine()._get_bm25()
    assert bm25._tokenize_fn is BM25Scorer._tokenize


def test_graphify_seed_shares_same_bm25():
    tg = ToolGraph()
    for t in _tools().values():
        tg.add_tool(t)
    tg.set_tokenizer(_whitespace_tokenize)
    engine = tg._get_retrieval_engine()
    bm25 = engine._get_bm25()
    # graphify seed selection calls tg._get_retrieval_engine()._get_bm25() — the
    # same cached instance, so the injected tokenizer applies to graphify too.
    assert engine._get_bm25() is bm25
    assert bm25._tokenize_fn is _whitespace_tokenize


# --- Kiwi optional tokenizer (skipped when the [korean] extra is absent) ---


def test_kiwi_korean_compound_splits_to_morphemes():
    pytest.importorskip("kiwipiepy")
    tok = KiwiTokenizer()
    tokens = tok("배송상태조회")
    assert "배송" in tokens
    assert "상태" in tokens
    assert "조회" in tokens
    # clean morphemes, no character-bigram noise ("송상", "태조")
    assert "송상" not in tokens
    assert "태조" not in tokens


def test_kiwi_preserves_english_pipeline():
    pytest.importorskip("kiwipiepy")
    tok = KiwiTokenizer()
    assert tok("getUserById") == ["get", "user", "by", "id"]


def test_kiwi_korean_retrieval_picks_correct_tool():
    pytest.importorskip("kiwipiepy")
    scorer = BM25Scorer(_tools(), tokenizer=KiwiTokenizer())
    scores = scorer.score("배송상태조회")
    assert scores
    assert max(scores, key=scores.get) == "trackShipment"
