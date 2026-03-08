"""Tests for embedding-based similarity search (Phase 2)."""

from __future__ import annotations

import math

import pytest

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.embedding import EmbeddingIndex

# ---------- helpers ----------


def _make_tool(name: str, desc: str = "", tags: list[str] | None = None) -> ToolSchema:
    return ToolSchema(name=name, description=desc, tags=tags or [])


def _make_tools_dict(*tools: ToolSchema) -> dict[str, ToolSchema]:
    return {t.name: t for t in tools}


# ---------- manual add / search ----------


class TestManualEmbedding:
    """Test manual add() + search() with hand-crafted embeddings."""

    def test_add_and_search(self):
        pytest.importorskip("numpy")
        idx = EmbeddingIndex()
        idx.add("tool_a", [1.0, 0.0, 0.0])
        idx.add("tool_b", [0.0, 1.0, 0.0])
        idx.add("tool_c", [0.7, 0.7, 0.0])

        results = idx.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        # tool_a should be the best match (exact)
        assert results[0][0] == "tool_a"
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)

    def test_search_empty(self):
        pytest.importorskip("numpy")
        idx = EmbeddingIndex()
        results = idx.search([1.0, 0.0], top_k=5)
        assert results == []

    def test_search_zero_query(self):
        pytest.importorskip("numpy")
        idx = EmbeddingIndex()
        idx.add("tool_a", [1.0, 0.0])
        results = idx.search([0.0, 0.0], top_k=5)
        assert results == []

    def test_top_k_limit(self):
        pytest.importorskip("numpy")
        idx = EmbeddingIndex()
        for i in range(10):
            idx.add(f"tool_{i}", [float(i), 1.0])
        results = idx.search([9.0, 1.0], top_k=3)
        assert len(results) == 3

    def test_size_property(self):
        idx = EmbeddingIndex()
        assert idx.size == 0
        idx.add("a", [1.0])
        assert idx.size == 1
        idx.add("b", [2.0])
        assert idx.size == 2

    def test_cosine_similarity_ordering(self):
        """Verify correct ordering by cosine similarity."""
        pytest.importorskip("numpy")
        idx = EmbeddingIndex()
        idx.add("parallel", [1.0, 0.0])
        idx.add("diagonal", [1.0, 1.0])
        idx.add("orthogonal", [0.0, 1.0])

        results = idx.search([1.0, 0.0], top_k=3)
        names = [r[0] for r in results]
        assert names == ["parallel", "diagonal", "orthogonal"]
        # parallel: cos=1.0, diagonal: cos=1/sqrt(2), orthogonal: cos=0.0
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)
        assert results[1][1] == pytest.approx(1.0 / math.sqrt(2), abs=1e-5)
        assert results[2][1] == pytest.approx(0.0, abs=1e-5)


# ---------- build_from_tools (requires sentence-transformers) ----------


class TestBuildFromTools:
    """Test automatic embedding with sentence-transformers."""

    def test_build_from_tools(self):
        pytest.importorskip("sentence_transformers")
        tools = _make_tools_dict(
            _make_tool("get_user", "Retrieve user information", ["user", "api"]),
            _make_tool("list_users", "List all users", ["user"]),
            _make_tool("send_email", "Send an email to a recipient", ["email"]),
        )
        idx = EmbeddingIndex(model_name="all-MiniLM-L6-v2")
        idx.build_from_tools(tools)
        assert idx.size == 3

        # Search for "user" — get_user and list_users should rank higher
        query_emb = idx.encode("user information")
        results = idx.search(query_emb, top_k=3)
        top_names = {r[0] for r in results[:2]}
        assert "get_user" in top_names or "list_users" in top_names

    def test_encode(self):
        pytest.importorskip("sentence_transformers")
        idx = EmbeddingIndex(model_name="all-MiniLM-L6-v2")
        emb = idx.encode("hello world")
        assert isinstance(emb, list)
        assert len(emb) > 0
        assert all(isinstance(v, float) for v in emb)

    def test_build_empty_tools(self):
        pytest.importorskip("sentence_transformers")
        idx = EmbeddingIndex(model_name="all-MiniLM-L6-v2")
        idx.build_from_tools({})
        assert idx.size == 0


# ---------- encode without model raises ValueError ----------


class TestErrors:
    def test_encode_without_provider(self):
        idx = EmbeddingIndex()  # no model_name, no provider
        with pytest.raises(ValueError, match="No embedding provider"):
            idx.encode("test")

    def test_numpy_import_error_message(self, monkeypatch):
        """Verify that missing numpy gives a user-friendly message."""
        import graph_tool_call.retrieval.embedding as emb_module

        def fake_require_numpy():
            raise ImportError(
                "numpy is required for embedding search. "
                "Install with: pip install graph-tool-call[embedding]"
            )

        monkeypatch.setattr(emb_module, "_require_numpy", fake_require_numpy)

        idx = EmbeddingIndex()
        idx.add("tool_a", [1.0, 0.0])
        with pytest.raises(ImportError, match="graph-tool-call\\[embedding\\]"):
            idx.search([1.0, 0.0])


# ---------- RetrievalEngine + embedding integration ----------


class TestRetrievalEngineIntegration:
    """Test that RetrievalEngine uses embedding scores when available."""

    def test_embedding_scores_in_rrf(self):
        """Embedding scores are included in RRF fusion."""
        pytest.importorskip("numpy")
        from graph_tool_call.core.graph import NetworkXGraph
        from graph_tool_call.ontology.schema import NodeType
        from graph_tool_call.retrieval.engine import RetrievalEngine

        graph = NetworkXGraph()
        tools = _make_tools_dict(
            _make_tool("get_user", "Retrieve user information"),
            _make_tool("list_users", "List all users"),
            _make_tool("send_email", "Send an email"),
        )
        for name in tools:
            graph.add_node(name, node_type=NodeType.TOOL)

        engine = RetrievalEngine(graph, tools)

        # Create an embedding index with manual embeddings
        idx = EmbeddingIndex()
        # Make send_email very close to query direction
        idx.add("get_user", [0.1, 0.9])
        idx.add("list_users", [0.2, 0.8])
        idx.add("send_email", [0.95, 0.05])

        engine.set_embedding_index(idx)

        # Verify weights were rebalanced
        assert engine._embedding_weight == 0.3
        assert engine._graph_weight == 0.45
        assert engine._keyword_weight == 0.25


# ---------- ToolGraph.enable_embedding integration ----------


class TestToolGraphEnableEmbedding:
    def test_enable_embedding(self):
        pytest.importorskip("sentence_transformers")
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "get_user",
                    "description": "Get user by ID",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            }
        )
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "list_users",
                    "description": "List all users",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        tg.enable_embedding()
        engine = tg._get_retrieval_engine()
        assert engine._embedding_index is not None
        assert engine._embedding_index.size == 2
