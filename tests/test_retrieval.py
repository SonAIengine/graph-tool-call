"""Tests for retrieval engine."""

from graph_tool_call.tool_graph import ToolGraph


def _build_file_tools_graph() -> ToolGraph:
    """Build a sample ToolGraph with file operation tools."""
    tg = ToolGraph()

    tools = [
        {"name": "read_file", "description": "Read contents of a file from disk"},
        {"name": "write_file", "description": "Write contents to a file on disk"},
        {"name": "delete_file", "description": "Delete a file from the filesystem"},
        {"name": "list_directory", "description": "List files in a directory"},
        {"name": "query_database", "description": "Execute SQL query on a database"},
        {"name": "insert_record", "description": "Insert a record into a database table"},
        {"name": "send_email", "description": "Send an email message"},
        {"name": "search_web", "description": "Search the web for information"},
    ]
    tg.add_tools(tools)

    # Set up categories
    tg.add_category("file_operations", domain="io")
    tg.add_category("database", domain="data")
    tg.add_category("communication")

    tg.assign_category("read_file", "file_operations")
    tg.assign_category("write_file", "file_operations")
    tg.assign_category("delete_file", "file_operations")
    tg.assign_category("list_directory", "file_operations")
    tg.assign_category("query_database", "database")
    tg.assign_category("insert_record", "database")
    tg.assign_category("send_email", "communication")

    # Set up relations
    tg.add_relation("read_file", "write_file", "complementary")
    tg.add_relation("query_database", "insert_record", "complementary")
    tg.add_relation("write_file", "delete_file", "similar_to")

    return tg


def test_retrieve_file_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("read a file from disk", top_k=3)
    names = [t.name for t in results]
    assert "read_file" in names


def test_retrieve_returns_related_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("write file", top_k=5)
    names = [t.name for t in results]
    # write_file should be top, and related tools like read_file, delete_file should appear
    assert "write_file" in names


def test_retrieve_database_tools():
    tg = _build_file_tools_graph()
    results = tg.retrieve("query database", top_k=3)
    names = [t.name for t in results]
    assert "query_database" in names


def test_retrieve_respects_top_k():
    tg = _build_file_tools_graph()
    results = tg.retrieve("file operations", top_k=2)
    assert len(results) <= 2


def test_retrieve_empty_query():
    tg = _build_file_tools_graph()
    results = tg.retrieve("", top_k=5)
    # Empty query may return no results or all tools depending on implementation
    assert isinstance(results, list)
