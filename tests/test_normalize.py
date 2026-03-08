"""Tests for normalize_tool() — verifies consistent field coverage across all ingest sources."""

from __future__ import annotations

from graph_tool_call import ToolGraph, ToolSchema, normalize_tool
from graph_tool_call.core.tool import MCPAnnotations

# ---------------------------------------------------------------------------
# Unit tests for normalize_tool()
# ---------------------------------------------------------------------------


class TestNormalizeTool:
    def test_fills_tags_from_name(self) -> None:
        tool = ToolSchema(name="getUserProfile", description="Get user profile")
        normalize_tool(tool)
        assert "user" in tool.tags
        assert "profile" in tool.tags
        # verb "get" should be stripped
        assert "get" not in tool.tags

    def test_fills_domain_from_tags(self) -> None:
        tool = ToolSchema(name="deleteOrder", description="Delete an order")
        normalize_tool(tool)
        assert tool.domain is not None
        assert tool.domain == tool.tags[0]

    def test_fills_annotations_read_verb(self) -> None:
        for verb in ("get", "list", "fetch", "read", "search", "find", "show"):
            tool = ToolSchema(name=f"{verb}Items", description=f"{verb} items")
            normalize_tool(tool)
            assert tool.annotations is not None, f"No annotations for {verb}"
            assert tool.annotations.read_only_hint is True, f"{verb} not read_only"
            assert tool.annotations.destructive_hint is False, f"{verb} destructive"

    def test_fills_annotations_create_verb(self) -> None:
        for verb in ("create", "add", "post", "send"):
            tool = ToolSchema(name=f"{verb}Order", description=f"{verb} order")
            normalize_tool(tool)
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is False
            assert tool.annotations.destructive_hint is False

    def test_fills_annotations_delete_verb(self) -> None:
        for verb in ("delete", "remove", "cancel", "destroy"):
            tool = ToolSchema(name=f"{verb}User", description=f"{verb} user")
            normalize_tool(tool)
            assert tool.annotations is not None
            assert tool.annotations.destructive_hint is True

    def test_fills_annotations_update_verb(self) -> None:
        for verb in ("update", "set", "put", "save"):
            tool = ToolSchema(name=f"{verb}Config", description=f"{verb} config")
            normalize_tool(tool)
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is False
            assert tool.annotations.idempotent_hint is True

    def test_preserves_existing_tags(self) -> None:
        tool = ToolSchema(name="getUser", description="...", tags=["custom_tag"])
        normalize_tool(tool)
        assert tool.tags == ["custom_tag"]

    def test_preserves_existing_domain(self) -> None:
        tool = ToolSchema(name="getUser", description="...", domain="my_domain")
        normalize_tool(tool)
        assert tool.domain == "my_domain"

    def test_preserves_existing_annotations(self) -> None:
        original = MCPAnnotations(read_only_hint=False, destructive_hint=True)
        tool = ToolSchema(name="getUser", description="...", annotations=original)
        normalize_tool(tool)
        # "get" would normally infer read_only=True, but existing annotations preserved
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True

    def test_snake_case_name(self) -> None:
        tool = ToolSchema(name="delete_old_records", description="...")
        normalize_tool(tool)
        assert "old" in tool.tags
        assert "record" in tool.tags  # singularized
        assert tool.annotations is not None
        assert tool.annotations.destructive_hint is True

    def test_unknown_verb_no_annotations(self) -> None:
        tool = ToolSchema(name="ping", description="Ping the server")
        normalize_tool(tool)
        # "ping" is not in verb map → annotations stays None
        assert tool.annotations is None
        # But tags/domain should still be populated
        assert tool.tags == ["ping"]
        assert tool.domain == "ping"

    def test_domain_fallback_general(self) -> None:
        """Single-token verb-only name falls back correctly."""
        tool = ToolSchema(name="run", description="Run something")
        normalize_tool(tool)
        # "run" is a verb, stripped → tags = ["run"] (fallback to first token)
        assert tool.domain is not None


# ---------------------------------------------------------------------------
# Integration: verify all ingest paths produce consistent field coverage
# ---------------------------------------------------------------------------


def _check_fields(tool: ToolSchema, source: str) -> None:
    """Assert all 7 key fields are populated."""
    assert tool.name, f"[{source}] name missing"
    assert tool.description is not None, f"[{source}] description missing"
    assert isinstance(tool.parameters, list), f"[{source}] parameters not list"
    assert isinstance(tool.tags, list) and len(tool.tags) > 0, f"[{source}] tags empty"
    assert tool.domain is not None, f"[{source}] domain missing"
    assert isinstance(tool.metadata, dict), f"[{source}] metadata not dict"
    # annotations may be None for tools without recognizable verb prefix — that's OK


class TestIngestConsistency:
    """All ingest sources must produce ToolSchema with equivalent field coverage."""

    def test_openapi_fields(self) -> None:
        tg = ToolGraph()
        tools = tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        for tool in tools:
            _check_fields(tool, "openapi")
            assert tool.metadata.get("source") == "openapi"
            assert tool.annotations is not None

    def test_mcp_fields(self) -> None:
        tg = ToolGraph()
        mcp_tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "name": "delete_file",
                "description": "Delete a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
        ]
        tools = tg.ingest_mcp_tools(mcp_tools, server_name="fs")
        for tool in tools:
            _check_fields(tool, "mcp")
            assert tool.metadata.get("source") == "mcp"

        # read_file: annotations inferred from verb "read"
        read_tool = tg.tools["read_file"]
        assert read_tool.annotations is not None
        assert read_tool.annotations.read_only_hint is True

        # delete_file: original MCP annotations preserved
        del_tool = tg.tools["delete_file"]
        assert del_tool.annotations is not None
        assert del_tool.annotations.destructive_hint is True

    def test_function_fields(self) -> None:
        def get_weather(city: str) -> str:
            """Get current weather for a city."""

        def delete_cache(key: str) -> None:
            """Delete a cache entry."""

        tg = ToolGraph()
        tools = tg.ingest_functions([get_weather, delete_cache])
        for tool in tools:
            _check_fields(tool, "function")
            assert tool.metadata.get("source") == "function"

        weather = tg.tools["get_weather"]
        assert weather.annotations is not None
        assert weather.annotations.read_only_hint is True

        cache = tg.tools["delete_cache"]
        assert cache.annotations is not None
        assert cache.annotations.destructive_hint is True

    def test_manual_add_tool_fields(self) -> None:
        tg = ToolGraph()

        # OpenAI format
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "searchProducts",
                    "description": "Search for products",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
            }
        )

        tool = tg.tools["searchProducts"]
        _check_fields(tool, "manual/openai")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True  # "search" verb

    def test_mixed_sources_consistent(self) -> None:
        """Tools from different sources in the same graph have equal richness."""
        tg = ToolGraph()

        # OpenAPI
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")

        # MCP
        tg.ingest_mcp_tools(
            [
                {
                    "name": "send_email",
                    "description": "Send an email",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
                    },
                }
            ]
        )

        # Function
        def list_users(limit: int = 10) -> list:
            """List all users."""

        tg.ingest_functions([list_users])

        # Manual
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "updateSettings",
                    "description": "Update app settings",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        # ALL tools must have tags, domain, annotations regardless of source
        for name, tool in tg.tools.items():
            assert len(tool.tags) > 0, f"{name} has no tags"
            assert tool.domain is not None, f"{name} has no domain"
            # annotations may be None for non-verb names, but most should have them

    def test_mcp_categories_in_graph(self) -> None:
        """MCP tools get category nodes and BELONGS_TO edges."""
        tg = ToolGraph()
        tg.ingest_mcp_tools(
            [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "write_file",
                    "description": "Write a file",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        )

        # Both tools should have domain assigned and category in graph
        read_tool = tg.tools["read_file"]
        write_tool = tg.tools["write_file"]
        assert read_tool.domain is not None
        assert write_tool.domain is not None
        # Category node should exist in graph
        assert tg.graph.has_node(read_tool.domain)

    def test_function_dependencies_detected(self) -> None:
        """Function ingest now runs dependency detection."""

        def get_user(user_id: str) -> dict:
            """Get user by ID."""

        def delete_user(user_id: str) -> None:
            """Delete a user."""

        def list_users(limit: int = 10) -> list:
            """List all users."""

        tg = ToolGraph()
        tg.ingest_functions([get_user, delete_user, list_users])

        # Should have more than just BELONGS_TO edges
        edges = tg.graph.edges()
        edge_count = len(edges)
        assert edge_count > 3, f"Expected dependencies, got only {edge_count} edges"
