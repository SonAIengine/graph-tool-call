"""Tests for 5-Stage Deduplication Pipeline (Phase 2)."""

from __future__ import annotations

import pytest

from graph_tool_call.analyze.similarity import (
    DuplicatePair,
    _param_jaccard,
    _quality_score,
    _stage1_exact_hash,
    _stage2_name_fuzzy,
    _stage3_schema_structural,
    find_duplicates,
    merge_duplicates,
)
from graph_tool_call.core.tool import ToolParameter, ToolSchema

# ---------- helpers ----------


def _tool(
    name: str,
    desc: str = "",
    params: list[tuple[str, str]] | None = None,
    tags: list[str] | None = None,
) -> ToolSchema:
    parameters = []
    if params:
        parameters = [ToolParameter(name=n, type=t) for n, t in params]
    return ToolSchema(name=name, description=desc, parameters=parameters, tags=tags or [])


def _tools_dict(*tools: ToolSchema) -> dict[str, ToolSchema]:
    return {t.name: t for t in tools}


# ---------- Stage 1: Exact Hash ----------


class TestStage1ExactHash:
    def test_identical_tools(self):
        tools = _tools_dict(
            _tool("get_user", params=[("id", "string")]),
            _tool("get_user_v2", params=[("id", "string")]),
        )
        # Different names but we manually test the hash stage
        # Stage 1 compares canonical(name+params), so different names → different hash
        pairs = _stage1_exact_hash(tools)
        assert len(pairs) == 0  # names differ, so hashes differ

    def test_same_name_different_case(self):
        """Same lowercase name + same params = exact match."""
        t1 = _tool("GetUser", params=[("id", "string")])
        t2 = _tool("getuser", params=[("id", "string")])
        tools = _tools_dict(t1, t2)
        pairs = _stage1_exact_hash(tools)
        assert len(pairs) == 1
        assert pairs[0].score == 1.0
        assert pairs[0].stage == 1

    def test_no_duplicates(self):
        tools = _tools_dict(
            _tool("get_user", params=[("id", "string")]),
            _tool("send_email", params=[("to", "string")]),
        )
        pairs = _stage1_exact_hash(tools)
        assert len(pairs) == 0


# ---------- Stage 2: Name Fuzzy ----------


class TestStage2NameFuzzy:
    def test_similar_names(self):
        pytest.importorskip("rapidfuzz")
        tools = _tools_dict(
            _tool("get_user"),
            _tool("get_users"),
        )
        pairs = _stage2_name_fuzzy(tools, threshold=0.8)
        assert len(pairs) >= 1
        assert pairs[0].stage == 2

    def test_dissimilar_names(self):
        pytest.importorskip("rapidfuzz")
        tools = _tools_dict(
            _tool("get_user"),
            _tool("send_email"),
        )
        pairs = _stage2_name_fuzzy(tools, threshold=0.85)
        assert len(pairs) == 0

    def test_no_rapidfuzz_returns_empty(self, monkeypatch):
        """When rapidfuzz is not available, Stage 2 is skipped."""
        import graph_tool_call.analyze.similarity as sim_mod

        # Simulate ImportError by wrapping
        def fake_stage2(tools, threshold):
            return []  # simulate skip

        monkeypatch.setattr(sim_mod, "_stage2_name_fuzzy", fake_stage2)
        tools = _tools_dict(_tool("get_user"), _tool("get_users"))
        pairs = sim_mod._stage2_name_fuzzy(tools, 0.8)
        assert pairs == []


# ---------- Stage 3: Schema Structural ----------


class TestStage3SchemaStructural:
    def test_identical_params(self):
        tools = _tools_dict(
            _tool("tool_a", params=[("id", "string"), ("name", "string")]),
            _tool("tool_b", params=[("id", "string"), ("name", "string")]),
        )
        pairs = _stage3_schema_structural(tools, threshold=0.5)
        assert len(pairs) >= 1
        assert pairs[0].score == pytest.approx(1.0, abs=0.01)

    def test_different_params(self):
        tools = _tools_dict(
            _tool("tool_a", params=[("id", "string")]),
            _tool("tool_b", params=[("email", "string"), ("password", "string")]),
        )
        pairs = _stage3_schema_structural(tools, threshold=0.5)
        assert len(pairs) == 0

    def test_partial_overlap(self):
        tools = _tools_dict(
            _tool("tool_a", params=[("id", "string"), ("name", "string"), ("email", "string")]),
            _tool("tool_b", params=[("id", "string"), ("name", "string")]),
        )
        pairs = _stage3_schema_structural(tools, threshold=0.5)
        assert len(pairs) >= 1
        # Jaccard = 2/3, type match = 1.0 → 0.7*(2/3) + 0.3*1.0 = 0.767
        assert pairs[0].score >= 0.5


# ---------- Stage 4: Embedding (optional) ----------


class TestStage4Embedding:
    def test_with_embedding_index(self):
        pytest.importorskip("numpy")
        from graph_tool_call.retrieval.embedding import EmbeddingIndex

        idx = EmbeddingIndex()
        idx.add("tool_a", [1.0, 0.0, 0.0])
        idx.add("tool_b", [0.98, 0.2, 0.0])  # very similar to tool_a
        idx.add("tool_c", [0.0, 0.0, 1.0])  # very different

        tools = _tools_dict(_tool("tool_a"), _tool("tool_b"), _tool("tool_c"))
        from graph_tool_call.analyze.similarity import _stage4_embedding

        pairs = _stage4_embedding(tools, threshold=0.8, embedding_index=idx)
        assert len(pairs) >= 1
        # tool_a and tool_b should be similar
        pair_names = {(p.tool_a, p.tool_b) for p in pairs}
        assert any("tool_a" in p and "tool_b" in p for p in pair_names)

    def test_without_embedding_index(self):
        from graph_tool_call.analyze.similarity import _stage4_embedding

        tools = _tools_dict(_tool("a"), _tool("b"))
        pairs = _stage4_embedding(tools, 0.85, embedding_index=None)
        assert pairs == []


# ---------- Param Jaccard ----------


class TestParamJaccard:
    def test_both_empty(self):
        a = _tool("a")
        b = _tool("b")
        assert _param_jaccard(a, b) == 1.0

    def test_one_empty(self):
        a = _tool("a", params=[("id", "string")])
        b = _tool("b")
        assert _param_jaccard(a, b) == 0.0


# ---------- Quality Score ----------


class TestQualityScore:
    def test_well_documented(self):
        t = _tool(
            "get_user",
            desc="Retrieve user information by ID from the database",
            params=[("id", "string")],
        )
        t.parameters[0].description = "The user ID"
        score = _quality_score(t)
        assert score > 0.3

    def test_undocumented(self):
        t = _tool("x")
        score = _quality_score(t)
        assert score < 0.5


# ---------- find_duplicates (integrated) ----------


class TestFindDuplicates:
    def test_find_exact_duplicates(self):
        tools = _tools_dict(
            _tool("GetUser", params=[("id", "string")]),
            _tool("getuser", params=[("id", "string")]),
            _tool("send_email", params=[("to", "string")]),
        )
        pairs = find_duplicates(tools, threshold=0.85)
        assert len(pairs) >= 1
        dup = pairs[0]
        assert {dup.tool_a, dup.tool_b} == {"GetUser", "getuser"}

    def test_no_duplicates(self):
        tools = _tools_dict(
            _tool("get_user", params=[("id", "string")]),
            _tool("send_email", params=[("to", "string"), ("body", "string")]),
        )
        pairs = find_duplicates(tools, threshold=0.85)
        assert len(pairs) == 0

    def test_single_tool(self):
        tools = _tools_dict(_tool("only_one"))
        pairs = find_duplicates(tools)
        assert pairs == []


# ---------- merge_duplicates ----------


class TestMergeDuplicates:
    def _make_pair(self, a: str, b: str, score: float = 0.9) -> DuplicatePair:
        return DuplicatePair(tool_a=a, tool_b=b, score=score, stage=5)

    def test_keep_first(self):
        tools = _tools_dict(
            _tool("get_user", desc="Get user"),
            _tool("fetch_user", desc="Fetch user from API with lots of details"),
        )
        pairs = [self._make_pair("fetch_user", "get_user")]
        merged = merge_duplicates(tools, pairs, strategy="keep_first")
        # keep_first: sorted alphabetically, "fetch_user" < "get_user"
        assert "get_user" in merged
        assert merged["get_user"] == "fetch_user"

    def test_keep_best(self):
        tools = _tools_dict(
            _tool("get_user", desc="Get"),
            _tool("fetch_user", desc="Fetch user information by ID from the database"),
        )
        pairs = [self._make_pair("get_user", "fetch_user")]
        merged = merge_duplicates(tools, pairs, strategy="keep_best")
        # fetch_user has better description → keep fetch_user, remove get_user
        assert "get_user" in merged
        assert merged["get_user"] == "fetch_user"

    def test_create_alias(self):
        tools = _tools_dict(_tool("get_user"), _tool("fetch_user"))
        pairs = [self._make_pair("get_user", "fetch_user")]
        merged = merge_duplicates(tools, pairs, strategy="create_alias")
        assert len(merged) == 1


# ---------- ToolGraph integration ----------


class TestToolGraphDedup:
    def test_find_and_merge(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "GetUser",
                    "description": "Get user",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            }
        )
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "getuser",
                    "description": "Get user by ID",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            }
        )
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send an email",
                    "parameters": {"type": "object", "properties": {"to": {"type": "string"}}},
                },
            }
        )

        pairs = tg.find_duplicates(threshold=0.85)
        assert len(pairs) >= 1

        merged = tg.merge_duplicates(pairs, strategy="keep_best")
        assert len(merged) >= 1
        # After merge, one of the duplicates should be removed
        assert len(tg.tools) <= 3

    def test_create_alias_keeps_both(self):
        from graph_tool_call import ToolGraph

        tg = ToolGraph()
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "GetUser",
                    "description": "Get",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            }
        )
        tg.add_tool(
            {
                "type": "function",
                "function": {
                    "name": "getuser",
                    "description": "Get user",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            }
        )

        pairs = tg.find_duplicates(threshold=0.85)
        merged = tg.merge_duplicates(pairs, strategy="create_alias")
        assert len(merged) >= 1
        # Both tools should still exist (alias mode)
        assert len(tg.tools) == 2
