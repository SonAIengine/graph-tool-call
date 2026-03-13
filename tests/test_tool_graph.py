"""Tests for ToolGraph facade and serialization."""

import json
from unittest.mock import MagicMock, patch

import pytest

from graph_tool_call import ToolGraph
from graph_tool_call.retrieval.embedding import EmbeddingIndex, OllamaEmbeddingProvider


def test_add_openai_tools():
    tg = ToolGraph()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        },
    ]
    schemas = tg.add_tools(tools)
    assert len(schemas) == 1
    assert schemas[0].name == "get_weather"
    assert tg.graph.has_node("get_weather")


def test_add_anthropic_tools():
    tg = ToolGraph()
    tools = [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]
    schemas = tg.add_tools(tools)
    assert schemas[0].name == "read_file"


def test_add_relation_and_retrieve():
    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
    )
    tg.add_relation("read_file", "write_file", "complementary")
    results = tg.retrieve("read file", top_k=5)
    names = [t.name for t in results]
    assert "read_file" in names


def test_save_and_load(tmp_path):
    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "tool_a", "description": "Tool A"},
            {"name": "tool_b", "description": "Tool B"},
        ]
    )
    tg.add_relation("tool_a", "tool_b", "requires")

    save_path = tmp_path / "graph.json"
    tg.save(save_path)

    # Verify JSON is valid
    data = json.loads(save_path.read_text())
    assert "graph" in data
    assert "tools" in data

    # Load and verify
    tg2 = ToolGraph.load(save_path)
    assert "tool_a" in tg2.tools
    assert "tool_b" in tg2.tools
    assert tg2.graph.has_edge("tool_a", "tool_b")


def test_save_and_load_metadata(tmp_path):
    tg = ToolGraph()
    tg.add_tools([{"name": "tool_x", "description": "X"}])

    save_path = tmp_path / "graph.json"
    tg.save(save_path, metadata={"source_url": "https://example.com", "custom": 42})

    # Verify metadata in JSON
    data = json.loads(save_path.read_text())
    assert data["metadata"]["source_url"] == "https://example.com"
    assert data["metadata"]["custom"] == 42
    assert "built_at" in data["metadata"]
    assert data["metadata"]["tool_count"] == 1

    # Load and verify metadata accessible
    tg2 = ToolGraph.load(save_path)
    assert tg2.metadata["source_url"] == "https://example.com"
    assert tg2.metadata["custom"] == 42


def test_save_and_load_retrieval_state(tmp_path):
    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "tool_a", "description": "alpha"},
            {"name": "tool_b", "description": "beta"},
        ]
    )
    engine = tg._get_retrieval_engine()
    idx = EmbeddingIndex(provider=OllamaEmbeddingProvider())
    idx.add("tool_a", [1.0, 0.0])
    idx.add("tool_b", [0.0, 1.0])
    engine.set_embedding_index(idx)
    engine.set_weights(keyword=0.2, graph=0.4, embedding=0.35, annotation=0.05)
    engine.set_diversity(0.6)

    save_path = tmp_path / "graph.json"
    tg.save(save_path)

    data = json.loads(save_path.read_text())
    assert "retrieval_state" in data
    assert data["retrieval_state"]["weights"]["embedding"] == 0.35
    assert "embedding_index" in data["retrieval_state"]

    tg2 = ToolGraph.load(save_path)
    engine2 = tg2._get_retrieval_engine()
    assert engine2._embedding_index is not None
    assert engine2._embedding_index.size == 2
    assert engine2._embedding_weight == 0.35
    assert engine2._graph_weight == 0.4
    assert engine2._keyword_weight == 0.2
    assert engine2._annotation_weight == 0.05
    assert engine2._diversity_lambda == 0.6


def test_loaded_embedding_state_can_encode_query(tmp_path):
    pytest.importorskip("numpy", reason="numpy required for embedding tests")
    tg = ToolGraph()
    tg.add_tools([{"name": "tool_a", "description": "alpha"}])
    engine = tg._get_retrieval_engine()
    idx = EmbeddingIndex(provider=OllamaEmbeddingProvider())
    idx.add("tool_a", [1.0, 0.0])
    engine.set_embedding_index(idx)

    save_path = tmp_path / "graph.json"
    tg.save(save_path)
    tg2 = ToolGraph.load(save_path)

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"embeddings": [[1.0, 0.0]]}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        results = tg2.retrieve("anything", top_k=1)
    assert len(results) == 1
    assert results[0].name == "tool_a"


def test_repr():
    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "a", "description": "A"},
            {"name": "b", "description": "B"},
        ]
    )
    r = repr(tg)
    assert "tools=2" in r


def test_category_workflow():
    tg = ToolGraph()
    tg.add_tools(
        [
            {"name": "read_file", "description": "Read file"},
            {"name": "write_file", "description": "Write file"},
        ]
    )
    tg.add_category("file_ops", domain="io")
    tg.assign_category("read_file", "file_ops")
    tg.assign_category("write_file", "file_ops")

    # Graph should have domain and category nodes
    assert tg.graph.has_node("file_ops")
    assert tg.graph.has_node("io")
