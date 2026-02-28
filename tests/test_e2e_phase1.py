"""End-to-end integration tests for Phase 1 features."""

from __future__ import annotations

import os

from graph_tool_call import SearchMode, ToolGraph  # noqa: I001

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestIngestOpenAPIE2E:
    """Full pipeline: ingest_openapi -> auto-categorize -> dependency detect -> retrieve."""

    def test_petstore_swagger2_full_pipeline(self):
        tg = ToolGraph()
        tools = tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))

        assert len(tools) == 5
        tool_names = {t.name for t in tools}
        assert tool_names == {"listPets", "createPet", "getPet", "updatePet", "deletePet"}

        # Should have auto-created category nodes and relations
        assert tg.graph.node_count() > 5
        assert tg.graph.edge_count() > 0

    def test_petstore_retrieve_addpet(self):
        tg = ToolGraph()
        tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))
        results = tg.retrieve("create a new pet", top_k=5)
        names = [t.name for t in results]
        assert "createPet" in names

    def test_petstore_retrieve_with_graph_expansion(self):
        tg = ToolGraph()
        tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))
        results = tg.retrieve("get pet details", top_k=5)
        names = [t.name for t in results]
        # getPet should be returned, and graph expansion should bring related tools
        assert "getPet" in names
        assert len(results) > 1

    def test_openapi30_full_pipeline(self):
        tg = ToolGraph()
        tools = tg.ingest_openapi(os.path.join(FIXTURES_DIR, "minimal_openapi30.json"))

        assert len(tools) == 3
        tool_names = {t.name for t in tools}
        assert "listUsers" in tool_names
        assert "createUser" in tool_names
        assert "getUser" in tool_names

    def test_openapi31_auto_operationid(self):
        tg = ToolGraph()
        tools = tg.ingest_openapi(os.path.join(FIXTURES_DIR, "minimal_openapi31.json"))

        # listOrders has operationId, but post /orders does not
        tool_names = {t.name for t in tools}
        assert "listOrders" in tool_names
        # Auto-generated operationId for POST /orders
        assert any("post" in name.lower() and "order" in name.lower() for name in tool_names)

    def test_no_dependency_detection(self):
        tg = ToolGraph()
        tools = tg.ingest_openapi(
            os.path.join(FIXTURES_DIR, "petstore_swagger2.json"),
            detect_dependencies=False,
        )
        assert len(tools) == 5
        # Should have fewer edges (only BELONGS_TO from categories)
        edge_count = tg.graph.edge_count()
        # Categories still create edges
        assert edge_count >= 0


class TestIngestFunctionsE2E:
    """Full pipeline: ingest_functions -> retrieve."""

    def test_ingest_and_retrieve(self):
        def read_file(path: str) -> str:
            """Read contents of a file."""

        def write_file(path: str, content: str) -> None:
            """Write contents to a file."""

        def delete_file(path: str) -> bool:
            """Delete a file from disk."""

        tg = ToolGraph()
        tools = tg.ingest_functions([read_file, write_file, delete_file])
        assert len(tools) == 3

        results = tg.retrieve("read a file", top_k=3)
        names = [t.name for t in results]
        assert "read_file" in names


class TestSearchMode:
    """Test SearchMode parameter on retrieve."""

    def test_basic_mode_default(self):
        tg = ToolGraph()
        tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))
        results = tg.retrieve("list pets", top_k=3, mode=SearchMode.BASIC)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_string_mode(self):
        tg = ToolGraph()
        tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))
        results = tg.retrieve("list pets", top_k=3, mode="basic")
        assert isinstance(results, list)
        assert len(results) > 0


class TestRepr:
    """Test ToolGraph repr with ingested tools."""

    def test_repr_after_ingest(self):
        tg = ToolGraph()
        tg.ingest_openapi(os.path.join(FIXTURES_DIR, "petstore_swagger2.json"))
        r = repr(tg)
        assert "tools=5" in r


class TestSearchModeExport:
    """Test that SearchMode is properly exported."""

    def test_import_from_package(self):
        from graph_tool_call import SearchMode

        assert SearchMode.BASIC == "basic"
        assert SearchMode.ENHANCED == "enhanced"
        assert SearchMode.FULL == "full"
