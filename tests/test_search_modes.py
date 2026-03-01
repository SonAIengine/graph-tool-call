"""Tests for Search Modes — Tier 1/2 (Phase 2)."""

from __future__ import annotations

import json

import pytest

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.engine import RetrievalEngine, SearchMode
from graph_tool_call.retrieval.search_llm import (
    ExpandedQuery,
    SearchLLM,
    _extract_json,
)

# ---------- helpers ----------


def _tool(name: str, desc: str = "", tags: list[str] | None = None) -> ToolSchema:
    return ToolSchema(name=name, description=desc, tags=tags or [])


def _make_engine(tools: dict[str, ToolSchema]) -> RetrievalEngine:
    from graph_tool_call.core.graph import NetworkXGraph
    from graph_tool_call.ontology.schema import NodeType

    graph = NetworkXGraph()
    for name in tools:
        graph.add_node(name, node_type=NodeType.TOOL)
    return RetrievalEngine(graph, tools)


# ---------- Mock SearchLLM ----------


class MockSearchLLM(SearchLLM):
    """Mock LLM that returns configured responses."""

    def __init__(
        self,
        expand_response: str = '{"keywords": [], "synonyms": [], "english": []}',
        decompose_response: str = '{"intents": []}',
    ):
        self._expand_response = expand_response
        self._decompose_response = decompose_response
        self.expand_calls: list[str] = []
        self.decompose_calls: list[str] = []

    def generate(self, prompt: str) -> str:
        if "keywords" in prompt or "synonyms" in prompt:
            return self._expand_response
        if "intents" in prompt or "Break down" in prompt:
            return self._decompose_response
        return "{}"


class TestMockSearchLLM:
    def test_expand_query(self):
        llm = MockSearchLLM(
            expand_response=json.dumps(
                {
                    "keywords": ["user", "profile"],
                    "synonyms": ["account", "member"],
                    "english": ["user", "profile"],
                }
            )
        )
        result = llm.expand_query("사용자 프로필 조회")
        assert isinstance(result, ExpandedQuery)
        assert "user" in result.keywords
        assert "account" in result.synonyms

    def test_decompose_intents(self):
        llm = MockSearchLLM(
            decompose_response=json.dumps(
                {
                    "intents": [
                        {"action": "cancel", "target": "order"},
                        {"action": "process", "target": "refund"},
                    ]
                }
            )
        )
        result = llm.decompose_intents("주문 취소하고 환불해줘")
        assert len(result) == 2
        assert result[0].action == "cancel"
        assert result[0].target == "order"
        assert result[0].to_query() == "cancel order"

    def test_invalid_json_expand(self):
        llm = MockSearchLLM(expand_response="not json at all")
        result = llm.expand_query("test")
        assert result.keywords == []
        assert result.synonyms == []

    def test_invalid_json_decompose(self):
        llm = MockSearchLLM(decompose_response="broken")
        result = llm.decompose_intents("test")
        assert result == []


# ---------- wRRF ----------


class TestWeightedRRF:
    def test_wrrf_basic(self):
        sources = [
            ({"a": 1.0, "b": 0.5}, 1.0),
            ({"b": 1.0, "c": 0.5}, 2.0),  # higher weight
        ]
        result = RetrievalEngine._wrrf_fuse(sources)
        # "b" appears in both with combined weight
        assert "b" in result
        assert "a" in result
        assert "c" in result
        # "b" should have the highest score (rank 1 in source 2 with weight 2.0)
        assert result["b"] > result["a"]

    def test_wrrf_single_source(self):
        sources = [({"x": 1.0, "y": 0.5}, 1.0)]
        result = RetrievalEngine._wrrf_fuse(sources)
        assert result["x"] > result["y"]

    def test_wrrf_weight_matters(self):
        sources_equal = [
            ({"a": 1.0}, 1.0),
            ({"b": 1.0}, 1.0),
        ]
        sources_weighted = [
            ({"a": 1.0}, 1.0),
            ({"b": 1.0}, 10.0),  # much higher weight
        ]
        result_equal = RetrievalEngine._wrrf_fuse(sources_equal)
        result_weighted = RetrievalEngine._wrrf_fuse(sources_weighted)
        # With equal weights, a and b have same score
        assert result_equal["a"] == pytest.approx(result_equal["b"])
        # With weighted, b should be much higher
        assert result_weighted["b"] > result_weighted["a"]


# ---------- ENHANCED mode ----------


class TestEnhancedMode:
    def test_enhanced_with_llm(self):
        tools = {
            "get_user": _tool("get_user", "Get user information"),
            "list_users": _tool("list_users", "List all users"),
            "send_email": _tool("send_email", "Send an email"),
            "get_profile": _tool("get_profile", "Get user profile"),
        }
        engine = _make_engine(tools)

        llm = MockSearchLLM(
            expand_response=json.dumps(
                {
                    "keywords": ["user", "profile", "account"],
                    "synonyms": ["member", "info"],
                    "english": ["user", "profile"],
                }
            )
        )

        results = engine.retrieve("user info", top_k=4, mode=SearchMode.ENHANCED, llm=llm)
        assert len(results) >= 1
        # With expanded keywords, user-related tools should appear
        result_names = {r.name for r in results}
        assert "get_user" in result_names or "get_profile" in result_names

    def test_enhanced_without_llm_falls_back(self):
        """ENHANCED mode without LLM should not crash, falls back to BASIC."""
        tools = {"get_user": _tool("get_user", "Get user")}
        engine = _make_engine(tools)

        results = engine.retrieve("user", top_k=5, mode=SearchMode.ENHANCED, llm=None)
        assert len(results) >= 1


# ---------- FULL mode ----------


class TestFullMode:
    def test_full_with_llm(self):
        tools = {
            "cancel_order": _tool("cancel_order", "Cancel an order"),
            "process_refund": _tool("process_refund", "Process a refund"),
            "list_orders": _tool("list_orders", "List all orders"),
            "get_user": _tool("get_user", "Get user information"),
        }
        engine = _make_engine(tools)

        llm = MockSearchLLM(
            expand_response=json.dumps(
                {
                    "keywords": ["cancel", "order", "refund"],
                    "synonyms": ["annul", "reimburse"],
                    "english": ["cancel", "order", "refund"],
                }
            ),
            decompose_response=json.dumps(
                {
                    "intents": [
                        {"action": "cancel", "target": "order"},
                        {"action": "process", "target": "refund"},
                    ]
                }
            ),
        )

        results = engine.retrieve("주문 취소하고 환불", top_k=4, mode=SearchMode.FULL, llm=llm)
        assert len(results) >= 1
        result_names = {r.name for r in results}
        # Intent decomposition should help find both cancel_order and process_refund
        assert "cancel_order" in result_names or "process_refund" in result_names

    def test_full_without_llm_falls_back(self):
        tools = {"get_user": _tool("get_user", "Get user")}
        engine = _make_engine(tools)

        results = engine.retrieve("user", top_k=5, mode=SearchMode.FULL, llm=None)
        assert len(results) >= 1


# ---------- ToolGraph integration ----------


class TestToolGraphSearchModes:
    def test_retrieve_with_llm_param(self):
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

        llm = MockSearchLLM(
            expand_response=json.dumps(
                {
                    "keywords": ["user", "list"],
                    "synonyms": ["users"],
                    "english": ["user"],
                }
            )
        )

        results = tg.retrieve("user", top_k=5, mode="enhanced", llm=llm)
        assert len(results) >= 1

    def test_retrieve_basic_no_llm(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "get_user",
                    "description": "Get user by ID",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        # Basic mode, no LLM — should work fine
        results = tg.retrieve("user", top_k=5, mode="basic")
        assert len(results) >= 1


# ---------- Helpers ----------


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_code_block(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
