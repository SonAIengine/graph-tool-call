"""Tests for automatic ontology construction (Phase 2)."""

from __future__ import annotations

import json

import pytest

from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.ontology.auto import (
    _auto_categorize_by_domain,
    _auto_categorize_by_tags,
    auto_organize,
)
from graph_tool_call.ontology.builder import OntologyBuilder
from graph_tool_call.ontology.llm_provider import (
    OntologyLLM,
    ToolSummary,
    _extract_json,
    _format_tools_list,
)
from graph_tool_call.ontology.schema import NodeType, RelationType

# ---------- helpers ----------


def _make_builder():
    from graph_tool_call.core.dict_graph import DictGraph

    return OntologyBuilder(DictGraph())


def _tool(
    name: str,
    desc: str = "",
    tags: list[str] | None = None,
    domain: str | None = None,
    params: list[str] | None = None,
) -> ToolSchema:
    parameters = [ToolParameter(name=p, type="string") for p in (params or [])]
    return ToolSchema(
        name=name, description=desc, tags=tags or [], domain=domain, parameters=parameters
    )


# ---------- Auto mode: tag-based ----------


class TestAutoByTags:
    def test_categorize_by_tags(self):
        builder = _make_builder()
        tools = [
            _tool("get_user", tags=["user"]),
            _tool("list_users", tags=["user"]),
            _tool("send_email", tags=["email"]),
        ]
        for t in tools:
            builder.add_tool(t)

        _auto_categorize_by_tags(builder, tools)

        # "user" and "email" categories should exist
        assert builder._graph.has_node("user")
        assert builder._graph.has_node("email")

        # Tools should be assigned
        user_tools = builder.get_tools_in_category("user")
        assert "get_user" in user_tools
        assert "list_users" in user_tools

    def test_no_tags(self):
        builder = _make_builder()
        tools = [_tool("get_user")]
        builder.add_tool(tools[0])
        _auto_categorize_by_tags(builder, tools)
        # No crash, no categories created
        assert builder._graph.node_count() == 1  # only the tool node


# ---------- Auto mode: domain-based ----------


class TestAutoByDomain:
    def test_categorize_by_domain(self):
        builder = _make_builder()
        tools = [
            _tool("get_user", domain="users"),
            _tool("send_email", domain="messaging"),
        ]
        for t in tools:
            builder.add_tool(t)

        _auto_categorize_by_domain(builder, tools)

        assert builder._graph.has_node("users")
        assert builder._graph.has_node("messaging")


# ---------- Auto mode: embedding clustering ----------


class TestAutoClusterByEmbedding:
    def test_clustering_creates_categories(self):
        pytest.importorskip("sentence_transformers")
        builder = _make_builder()
        tools = [
            _tool("get_user", "Retrieve user information by ID"),
            _tool("list_users", "List all users"),
            _tool("create_user", "Create a new user"),
            _tool("send_email", "Send an email to a recipient"),
            _tool("list_emails", "List all sent emails"),
            _tool("delete_email", "Delete an email"),
        ]
        for t in tools:
            builder.add_tool(t)

        from graph_tool_call.ontology.auto import _auto_cluster_by_embedding

        _auto_cluster_by_embedding(builder, tools)

        # Should have created at least one cluster category
        nodes = builder._graph.nodes()
        category_nodes = [
            n
            for n in nodes
            if builder._graph.has_node(n)
            and builder._graph.get_node_attrs(n).get("node_type") == NodeType.CATEGORY
        ]
        assert len(category_nodes) >= 1


# ---------- LLM provider helpers ----------


class TestLLMProviderHelpers:
    def test_format_tools_list(self):
        tools = [
            ToolSummary(name="get_user", description="Get user", parameters=["id"]),
            ToolSummary(name="send_email", description="Send email", parameters=["to", "body"]),
        ]
        result = _format_tools_list(tools)
        assert "get_user" in result
        assert "send_email" in result

    def test_extract_json_plain(self):
        text = '[{"key": "value"}]'
        result = _extract_json(text)
        assert result == [{"key": "value"}]

    def test_extract_json_code_block(self):
        text = '```json\n[{"key": "value"}]\n```'
        result = _extract_json(text)
        assert result == [{"key": "value"}]


# ---------- Mock LLM provider ----------


class MockOntologyLLM(OntologyLLM):
    """Mock LLM for testing. Returns pre-configured responses."""

    def __init__(
        self,
        relation_response: str = "[]",
        category_response: str = '{"categories": {}}',
        keyword_response: str = "{}",
    ):
        self._relation_response = relation_response
        self._category_response = category_response
        self._keyword_response = keyword_response
        self._calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self._calls.append(prompt)
        if "relationship" in prompt.lower():
            return self._relation_response
        if "categories" in prompt.lower() or "group" in prompt.lower():
            return self._category_response
        if "keyword" in prompt.lower() or "search" in prompt.lower():
            return self._keyword_response
        return "[]"


class TestMockLLM:
    def test_infer_relations(self):
        llm = MockOntologyLLM(
            relation_response=json.dumps(
                [
                    {
                        "source": "createUser",
                        "target": "getUser",
                        "relation": "REQUIRES",
                        "confidence": 0.9,
                        "reason": "getUser needs createUser",
                    }
                ]
            )
        )
        tools = [
            ToolSummary(name="createUser", description="Create user", parameters=["name"]),
            ToolSummary(name="getUser", description="Get user", parameters=["id"]),
        ]
        relations = llm.infer_relations(tools)
        assert len(relations) == 1
        assert relations[0].source == "createUser"
        assert relations[0].target == "getUser"
        assert relations[0].relation_type == RelationType.REQUIRES

    def test_suggest_categories(self):
        llm = MockOntologyLLM(
            category_response=json.dumps(
                {
                    "categories": {
                        "user_management": ["createUser", "getUser"],
                        "messaging": ["sendEmail"],
                    }
                }
            )
        )
        tools = [
            ToolSummary(name="createUser", description="Create", parameters=[]),
            ToolSummary(name="getUser", description="Get", parameters=[]),
            ToolSummary(name="sendEmail", description="Send", parameters=[]),
        ]
        categories = llm.suggest_categories(tools)
        assert "user_management" in categories
        assert "createUser" in categories["user_management"]

    def test_invalid_json_returns_empty(self):
        llm = MockOntologyLLM(relation_response="not json")
        tools = [ToolSummary(name="a", description="b", parameters=[])]
        relations = llm.infer_relations(tools)
        assert relations == []


# ---------- auto_organize integration ----------


class TestAutoOrganizeIntegration:
    def test_auto_without_llm(self):
        builder = _make_builder()
        tools = [
            _tool("get_user", "Get user", tags=["user"]),
            _tool("list_users", "List users", tags=["user"]),
        ]
        for t in tools:
            builder.add_tool(t)

        auto_organize(builder, tools)

        # Tags should create "user" category
        assert builder._graph.has_node("user")

    def test_auto_with_mock_llm(self):
        builder = _make_builder()
        tools = [
            _tool("createUser", "Create a new user", params=["name", "email"]),
            _tool("getUser", "Get user by ID", params=["id"]),
        ]
        for t in tools:
            builder.add_tool(t)

        llm = MockOntologyLLM(
            relation_response=json.dumps(
                [
                    {
                        "source": "createUser",
                        "target": "getUser",
                        "relation": "REQUIRES",
                        "confidence": 0.9,
                        "reason": "Need to create before getting",
                    }
                ]
            ),
            category_response=json.dumps(
                {"categories": {"user_management": ["createUser", "getUser"]}}
            ),
        )

        auto_organize(builder, tools, llm=llm)

        # LLM should have been called
        assert len(llm._calls) >= 1

        # Category from LLM
        assert builder._graph.has_node("user_management")


# ---------- ToolGraph.auto_organize integration ----------


class TestToolGraphAutoOrganize:
    def test_auto_organize_no_error(self):
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

        # Should not raise NotImplementedError anymore
        tg.auto_organize()


class TestLLMKeywordSyncToToolSchema:
    """Verify that LLM-enriched keywords sync back to ToolSchema for BM25."""

    def test_keywords_sync_to_tool_tags(self):
        builder = _make_builder()
        tools = [
            _tool("listPods", "list pods in namespace", tags=["pod"]),
            _tool("createPod", "create a new pod", tags=["pod"]),
        ]
        for t in tools:
            builder.add_tool(t)

        llm = MockOntologyLLM(
            keyword_response=json.dumps(
                {
                    "listPods": ["kubernetes", "container", "workload"],
                    "createPod": ["deploy", "schedule", "container"],
                }
            ),
        )

        auto_organize(builder, tools, llm=llm)

        # Enriched keywords should be in ToolSchema.tags (not just graph attrs)
        assert "kubernetes" in tools[0].tags
        assert "container" in tools[0].tags
        assert "deploy" in tools[1].tags

    def test_categories_sync_to_tool_tags(self):
        builder = _make_builder()
        tools = [
            _tool("listPods", "list pods"),
            _tool("createPod", "create pod"),
        ]
        for t in tools:
            builder.add_tool(t)

        llm = MockOntologyLLM(
            category_response=json.dumps(
                {"categories": {"pod_management": ["listPods", "createPod"]}}
            ),
        )

        auto_organize(builder, tools, llm=llm)

        # Category name should be in ToolSchema.tags
        assert "pod_management" in tools[0].tags
        assert "pod_management" in tools[1].tags

    def test_auto_organize_invalidates_retrieval_cache(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "listPods",
                    "description": "List pods",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        # Force retrieval engine creation
        tg.retrieve("list pods", top_k=1)
        assert tg._retrieval is not None

        # auto_organize should invalidate
        tg.auto_organize()
        assert tg._retrieval is None

    def test_enriched_keywords_visible_to_bm25(self):
        """End-to-end: LLM keywords should improve BM25 retrieval."""
        from graph_tool_call import ToolGraph
        from graph_tool_call.ontology.llm_provider import wrap_llm

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "connectProxy",
                    "description": "Connect to proxy endpoint",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "listNodes",
                    "description": "List all nodes",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        # Before enrichment: "reverse proxy" may not find connectProxy well
        tg.retrieve("reverse proxy load balancer", top_k=2)

        # Mock LLM that adds relevant keywords
        llm = MockOntologyLLM(
            keyword_response=json.dumps(
                {
                    "connectProxy": ["reverse proxy", "load balancer", "ingress"],
                }
            ),
        )
        wrapped = wrap_llm(llm)
        from graph_tool_call.ontology.auto import auto_organize as _auto_org

        _auto_org(tg._builder, list(tg._tools.values()), wrapped)
        tg._invalidate_retrieval()

        # After enrichment: "reverse proxy load balancer" should find connectProxy
        results_after = tg.retrieve("reverse proxy load balancer", top_k=2)
        names_after = [r.name for r in results_after]
        assert "connectProxy" in names_after
