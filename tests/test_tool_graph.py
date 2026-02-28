"""Tests for ToolGraph facade and serialization."""

import json
import tempfile
from pathlib import Path

from graph_tool_call import ToolGraph


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
    tg.add_tools([
        {"name": "read_file", "description": "Read a file"},
        {"name": "write_file", "description": "Write a file"},
    ])
    tg.add_relation("read_file", "write_file", "complementary")
    results = tg.retrieve("read file", top_k=5)
    names = [t.name for t in results]
    assert "read_file" in names


def test_save_and_load(tmp_path):
    tg = ToolGraph()
    tg.add_tools([
        {"name": "tool_a", "description": "Tool A"},
        {"name": "tool_b", "description": "Tool B"},
    ])
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


def test_repr():
    tg = ToolGraph()
    tg.add_tools([
        {"name": "a", "description": "A"},
        {"name": "b", "description": "B"},
    ])
    r = repr(tg)
    assert "tools=2" in r


def test_category_workflow():
    tg = ToolGraph()
    tg.add_tools([
        {"name": "read_file", "description": "Read file"},
        {"name": "write_file", "description": "Write file"},
    ])
    tg.add_category("file_ops", domain="io")
    tg.assign_category("read_file", "file_ops")
    tg.assign_category("write_file", "file_ops")

    # Graph should have domain and category nodes
    assert tg.graph.has_node("file_ops")
    assert tg.graph.has_node("io")
