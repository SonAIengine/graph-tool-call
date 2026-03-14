"""Tests for GraphEngine implementations (DictGraph + NetworkXGraph)."""

import pytest

from graph_tool_call.core.dict_graph import DictGraph

try:
    import networkx  # noqa: F401

    from graph_tool_call.core.graph import NetworkXGraph

    _HAS_NETWORKX = True
except ImportError:
    NetworkXGraph = None
    _HAS_NETWORKX = False

_networkx_skip = pytest.mark.skipif(not _HAS_NETWORKX, reason="networkx not installed")


def _graph_impls():
    """Yield graph implementations to test."""
    yield DictGraph
    yield pytest.param(NetworkXGraph, id="networkx", marks=_networkx_skip)


@pytest.fixture(params=list(_graph_impls()))
def graph_cls(request):
    return request.param


def test_add_and_has_node(graph_cls):
    g = graph_cls()
    g.add_node("a", label="A")
    assert g.has_node("a")
    assert not g.has_node("b")


def test_node_attrs(graph_cls):
    g = graph_cls()
    g.add_node("a", color="red")
    assert g.get_node_attrs("a") == {"color": "red"}
    g.set_node_attrs("a", color="blue", size=10)
    assert g.get_node_attrs("a") == {"color": "blue", "size": 10}


def test_add_and_has_edge(graph_cls):
    g = graph_cls()
    g.add_node("a")
    g.add_node("b")
    g.add_edge("a", "b", weight=0.5)
    assert g.has_edge("a", "b")
    assert not g.has_edge("b", "a")
    assert g.get_edge_attrs("a", "b") == {"weight": 0.5}


def test_remove_node(graph_cls):
    g = graph_cls()
    g.add_node("a")
    g.add_node("b")
    g.add_edge("a", "b")
    g.remove_node("a")
    assert not g.has_node("a")
    assert g.node_count() == 1


def test_neighbors(graph_cls):
    g = graph_cls()
    g.add_node("a")
    g.add_node("b")
    g.add_node("c")
    g.add_edge("a", "b")
    g.add_edge("c", "a")

    out_neighbors = g.get_neighbors("a", direction="out")
    assert "b" in out_neighbors

    in_neighbors = g.get_neighbors("a", direction="in")
    assert "c" in in_neighbors

    both_neighbors = g.get_neighbors("a", direction="both")
    assert "b" in both_neighbors
    assert "c" in both_neighbors


def test_bfs(graph_cls):
    g = graph_cls()
    for n in ["a", "b", "c", "d", "e"]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "d")
    g.add_edge("d", "e")

    result = g.bfs("a", max_depth=2)
    assert "a" in result
    assert "b" in result
    assert "c" in result
    assert "d" not in result  # depth 3


def test_subgraph(graph_cls):
    g = graph_cls()
    for n in ["a", "b", "c"]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("a", "c")

    sg = g.subgraph(["a", "b"])
    assert sg.has_node("a")
    assert sg.has_node("b")
    assert not sg.has_node("c")
    assert sg.has_edge("a", "b")


def test_serialization_roundtrip(graph_cls):
    g = graph_cls()
    g.add_node("a", label="A")
    g.add_node("b", label="B")
    g.add_edge("a", "b", weight=0.5)

    data = g.to_dict()
    g2 = graph_cls.from_dict(data)

    assert g2.has_node("a")
    assert g2.has_node("b")
    assert g2.has_edge("a", "b")
    assert g2.get_node_attrs("a")["label"] == "A"
    assert g2.get_edge_attrs("a", "b")["weight"] == 0.5


def test_edges_list(graph_cls):
    g = graph_cls()
    g.add_node("a")
    g.add_node("b")
    g.add_edge("a", "b", relation="requires")

    edges = g.edges()
    assert len(edges) == 1
    assert edges[0] == ("a", "b", {"relation": "requires"})


def test_dict_graph_cross_compat_with_networkx_format():
    """DictGraph.from_dict should load data serialized by NetworkXGraph and vice-versa."""
    data = {
        "nodes": [
            {"id": "x", "label": "X"},
            {"id": "y", "label": "Y"},
        ],
        "edges": [
            {"source": "x", "target": "y", "weight": 1.0},
        ],
    }
    g = DictGraph.from_dict(data)
    assert g.has_node("x")
    assert g.has_edge("x", "y")
    assert g.get_edge_attrs("x", "y")["weight"] == 1.0

    # Round-trip
    data2 = g.to_dict()
    assert len(data2["nodes"]) == 2
    assert len(data2["edges"]) == 1
