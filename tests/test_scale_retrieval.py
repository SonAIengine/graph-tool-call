"""Unit tests for A-P1-5 scale retrieval: prefilter, dynamic-k, BM25 restrict.

Focus on the recall-preserving guarantees (prefilter never drops BM25-top;
prefilter on == prefilter off recall) and the opt-in nature (small corpora and
default flags are unchanged).
"""

from __future__ import annotations

import json

import pytest

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.retrieval.engine import elbow_cut_k
from graph_tool_call.retrieval.intent import classify_intent
from graph_tool_call.retrieval.keyword import BM25Scorer
from graph_tool_call.retrieval.prefilter import CategoryPrefilter

_DOMAINS = ["pods", "orders", "users", "files", "payments", "repos", "issues", "nodes"]
_ACTIONS = ["get", "list", "create", "update", "delete", "search"]


def _big_graph(n: int = 600) -> ToolGraph:
    """Build a ToolGraph with >=500 namespaced tools across categories.

    Assigns each tool to a CATEGORY node (as OpenAPI ingest would) so the
    category prefilter has structure to match against.
    """
    tg = ToolGraph()
    for i in range(n):
        dom = _DOMAINS[i % len(_DOMAINS)]
        act = _ACTIONS[i % len(_ACTIONS)]
        name = f"{act}_{dom}_{i}"
        tg.add_tool(
            ToolSchema(
                name=name,
                description=f"{act} {dom} resource number {i}",
                parameters=[ToolParameter(name=f"{dom}_id", type="string")],
                tags=[dom, act],
                domain=dom,
            )
        )
        tg._builder.assign_category(name, dom)
    return tg


# ---------------------------------------------------------------------------
# elbow_cut_k
# ---------------------------------------------------------------------------


def test_elbow_cut_confident_returns_few():
    # top score dominates, sharp drop after #2 → keep 2
    assert elbow_cut_k([1.0, 0.95, 0.2, 0.1, 0.05], k=5) == 2


def test_elbow_cut_ambiguous_returns_k():
    # flat scores → no confident elbow → full k
    assert elbow_cut_k([0.5, 0.49, 0.48, 0.47, 0.46], k=5) == 5


def test_elbow_cut_short_list():
    assert elbow_cut_k([0.9], k=5) == 1
    assert elbow_cut_k([], k=5) == 0


def test_elbow_cut_respects_min_k():
    # even with an immediate drop, never below min_k
    assert elbow_cut_k([1.0, 0.1, 0.05], k=5, min_k=2) == 2


# ---------------------------------------------------------------------------
# BM25 restrict
# ---------------------------------------------------------------------------


def test_bm25_restrict_limits_scope():
    tg = _big_graph(120)
    bm25 = BM25Scorer(tg.tools)
    full = bm25.score("list pods")
    subset = set(list(full)[:5])
    restricted = bm25.score("list pods", restrict=subset)
    assert set(restricted).issubset(subset)
    # restricted scores equal the full scores for those tools (same math)
    for name in restricted:
        assert abs(restricted[name] - full[name]) < 1e-9


def test_bm25_restrict_none_is_identical():
    tg = _big_graph(120)
    bm25 = BM25Scorer(tg.tools)
    assert bm25.score("delete orders") == bm25.score("delete orders", restrict=None)


# ---------------------------------------------------------------------------
# CategoryPrefilter
# ---------------------------------------------------------------------------


def test_prefilter_unions_bm25_top_recall_guard():
    tg = _big_graph(600)
    pf = CategoryPrefilter(tg._graph, tg.tools)
    # Real tool names from the corpus, but from an UNRELATED category (orders)
    # so they can only enter the pool via the BM25 recall guard, not category
    # matching — a strict test of the union.
    bm25_top = [n for n in tg.tools if "orders" in n][:2]
    assert len(bm25_top) == 2
    pool = pf.candidate_pool("list pods", classify_intent("list pods"), bm25_top)
    assert pool is not None
    # recall guard: every BM25-top hit is retained even though it's off-category
    for name in bm25_top:
        assert name in pool
    # and it actually narrowed the corpus
    assert len(pool) < len(tg.tools)


def test_prefilter_none_on_weak_signal():
    tg = _big_graph(600)
    pf = CategoryPrefilter(tg._graph, tg.tools)
    # a query with no category/token overlap → no signal → None (full corpus)
    pool = pf.candidate_pool("zzqqxx nonsense gibberish", classify_intent("zzqqxx"), [])
    assert pool is None


def test_prefilter_pool_respects_max_pool():
    tg = _big_graph(600)
    pf = CategoryPrefilter(tg._graph, tg.tools, min_pool=50, max_pool=120)
    bm25_top = list(tg.tools)[:50]
    pool = pf.candidate_pool("get pods orders users files", classify_intent("get pods"), bm25_top)
    if pool is not None:
        # cap honoured (bm25_top guaranteed, so allow the 50 guard + cap headroom)
        assert len(pool) <= 120 + len(bm25_top)


# ---------------------------------------------------------------------------
# recall preservation in the full engine (the gate)
# ---------------------------------------------------------------------------


def test_prefilter_preserves_engine_recall():
    tg = _big_graph(600)
    queries = ["list pods", "delete orders", "create users", "search files", "update payments"]

    def top5(pf_on: bool) -> list[list[str]]:
        eng = tg._get_retrieval_engine()
        eng.enable_prefilter(pf_on)
        return [[t.name for t in tg.retrieve(q, top_k=5)] for q in queries]

    off = top5(False)
    on = top5(True)
    # Prefilter must not drop any result the full-corpus path returned.
    for q, o, n in zip(queries, off, on, strict=True):
        assert set(o).issubset(set(n)) or set(o) == set(n), f"recall regressed for {q!r}"


def test_prefilter_inactive_below_500():
    tg = _big_graph(200)  # < 500 → prefilter never fires
    eng = tg._get_retrieval_engine()
    eng.enable_prefilter(True)
    before = [t.name for t in tg.retrieve("list pods", top_k=5)]
    eng.enable_prefilter(False)
    after = [t.name for t in tg.retrieve("list pods", top_k=5)]
    assert before == after, "under 500 tools the prefilter must be a no-op"


# ---------------------------------------------------------------------------
# tune_for_scale wiring
# ---------------------------------------------------------------------------


def test_tune_for_scale_enables_flags():
    tg = _big_graph(200)
    tg.tune_for_scale()
    eng = tg._get_retrieval_engine()
    assert eng._prefilter_enabled is True
    assert eng._diversity_lambda == 0.7
    assert tg._adaptive_k_default is True


# ---------------------------------------------------------------------------
# search_tools pagination + dynamic-k (via as_tools gateway)
# ---------------------------------------------------------------------------


def _search_fn(tg: ToolGraph, **kwargs):
    search_tools, _call = tg.as_tools(**kwargs)
    return search_tools


def test_search_tools_pagination_fields_and_slicing():
    tg = _big_graph(200)
    search = _search_fn(tg, top_k=5)
    p1 = json.loads(search.invoke({"query": "list pods", "top_k": 5, "page": 1}))
    p2 = json.loads(search.invoke({"query": "list pods", "top_k": 5, "page": 2}))
    assert p1["page"] == 1 and p2["page"] == 2
    assert "has_more" in p1
    assert len(p1["tools"]) <= 5 and len(p2["tools"]) <= 5
    # pages don't overlap
    n1 = {t["name"] for t in p1["tools"]}
    n2 = {t["name"] for t in p2["tools"]}
    assert n1.isdisjoint(n2)


def test_search_tools_backward_compatible_default():
    """Without adaptive_k, page 1 returns the full top_k (no dynamic trim)."""
    tg = _big_graph(200)
    search = _search_fn(tg, top_k=5)  # adaptive_k defaults off
    out = json.loads(search.invoke({"query": "list pods"}))
    assert out["page"] == 1
    assert len(out["tools"]) == 5


def test_search_tools_adaptive_k_trims_confident_query():
    """A query that matches one tool near-exactly should trim below top_k."""
    tg = ToolGraph()
    # one obviously-dominant tool + many unrelated ones
    tg.add_tool(
        ToolSchema(name="reticulateSplines", description="reticulate the splines", domain="misc")
    )
    for i in range(30):
        tg.add_tool(ToolSchema(name=f"unrelated_{i}", description=f"thing {i}", domain="misc"))
    search = _search_fn(tg, top_k=10, adaptive_k=True)
    out = json.loads(search.invoke({"query": "reticulate splines"}))
    names = [t["name"] for t in out["tools"]]
    assert names[0] == "reticulateSplines"
    assert len(names) < 10, "confident query should dynamically trim"


@pytest.mark.parametrize("adaptive", [None, False, True])
def test_as_tools_adaptive_k_flag_threads(adaptive):
    tg = _big_graph(60)
    tools = tg.as_tools(top_k=5, adaptive_k=adaptive)
    assert len(tools) == 2  # search_tools + call_tool
