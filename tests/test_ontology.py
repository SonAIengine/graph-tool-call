"""Tests for ontology builder."""

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.schema import NodeType, RelationType


def _make_tool(name: str, desc: str = "") -> ToolSchema:
    return ToolSchema(name=name, description=desc)


def test_add_tool_creates_node():
    builder = OntologyBuilder()
    builder.add_tool(_make_tool("read_file", "Read a file"))
    assert builder.graph.has_node("read_file")
    attrs = builder.graph.get_node_attrs("read_file")
    assert attrs["node_type"] == NodeType.TOOL


def test_add_category_and_domain():
    builder = OntologyBuilder()
    builder.add_domain("io_operations")
    builder.add_category("file_ops", domain="io_operations")
    assert builder.graph.has_node("io_operations")
    assert builder.graph.has_node("file_ops")
    assert builder.graph.has_edge("file_ops", "io_operations")


def test_assign_category():
    builder = OntologyBuilder()
    builder.add_tool(_make_tool("read_file"))
    builder.add_category("file_ops")
    builder.assign_category("read_file", "file_ops")

    cats = builder.get_categories_for_tool("read_file")
    assert "file_ops" in cats


def test_get_tools_in_category():
    builder = OntologyBuilder()
    builder.add_category("file_ops")
    for name in ["read_file", "write_file", "delete_file"]:
        builder.add_tool(_make_tool(name))
        builder.assign_category(name, "file_ops")

    tools = builder.get_tools_in_category("file_ops")
    assert set(tools) == {"read_file", "write_file", "delete_file"}


def test_add_relation():
    builder = OntologyBuilder()
    builder.add_tool(_make_tool("read_file"))
    builder.add_tool(_make_tool("write_file"))
    builder.add_relation("read_file", "write_file", RelationType.COMPLEMENTARY)

    related = builder.get_related_tools("read_file")
    assert len(related) == 1
    assert related[0] == ("write_file", RelationType.COMPLEMENTARY)


def test_get_related_tools_filtered():
    builder = OntologyBuilder()
    builder.add_tool(_make_tool("query_db"))
    builder.add_tool(_make_tool("create_table"))
    builder.add_tool(_make_tool("search_db"))
    builder.add_relation("query_db", "create_table", RelationType.REQUIRES)
    builder.add_relation("query_db", "search_db", RelationType.SIMILAR_TO)

    requires = builder.get_related_tools("query_db", relation=RelationType.REQUIRES)
    assert len(requires) == 1
    assert requires[0][0] == "create_table"

    similar = builder.get_related_tools("query_db", relation=RelationType.SIMILAR_TO)
    assert len(similar) == 1
    assert similar[0][0] == "search_db"
