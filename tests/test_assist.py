"""Tests for the assist module: validation, correction, and next-step suggestion."""

from __future__ import annotations

from graph_tool_call import RetrievalResult, ToolCallDecision, ToolCallPolicy, ToolGraph

# ---------------------------------------------------------------------------
# validate_tool_call()
# ---------------------------------------------------------------------------


class TestValidateToolCall:
    def _make_graph(self) -> ToolGraph:
        tg = ToolGraph()
        tg.add_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "deleteUser",
                        "description": "Delete a user",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string", "description": "User ID"},
                                "force": {"type": "boolean", "description": "Force delete"},
                            },
                            "required": ["user_id"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "getUser",
                        "description": "Get user by ID",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"},
                            },
                            "required": ["user_id"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "listUsers",
                        "description": "List all users",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ["active", "inactive", "banned"],
                                },
                            },
                        },
                    },
                },
            ]
        )
        return tg

    def test_valid_call(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "deleteUser", "arguments": {"user_id": "123"}})
        assert result.valid
        assert result.tool_name == "deleteUser"
        assert result.arguments == {"user_id": "123"}

    def test_name_typo_correction(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "deleteuser", "arguments": {"user_id": "123"}})
        assert not result.valid
        assert result.tool_name == "deleteUser"
        assert "name" in result.corrections

    def test_unknown_tool(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "destroyDatabase", "arguments": {}})
        assert not result.valid
        assert any("unknown tool" in e for e in result.errors)

    def test_missing_required_param(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "deleteUser", "arguments": {}})
        assert not result.valid
        assert any("missing required" in e for e in result.errors)

    def test_param_name_correction(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "deleteUser", "arguments": {"User_Id": "123"}})
        # Should correct User_Id → user_id
        assert result.tool_name == "deleteUser"
        assert "user_id" in result.arguments
        assert result.arguments["user_id"] == "123"

    def test_enum_case_correction(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "listUsers", "arguments": {"status": "Active"}})
        assert result.tool_name == "listUsers"
        assert result.arguments["status"] == "active"

    def test_destructive_warning(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "deleteUser", "arguments": {"user_id": "123"}})
        assert any("destructive" in w for w in result.warnings)

    def test_openai_format(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call(
            {"function": {"name": "getUser", "arguments": {"user_id": "abc"}}}
        )
        assert result.valid
        assert result.tool_name == "getUser"

    def test_json_string_arguments(self) -> None:
        tg = self._make_graph()
        result = tg.validate_tool_call({"name": "getUser", "arguments": '{"user_id": "abc"}'})
        assert result.tool_name == "getUser"
        assert result.arguments == {"user_id": "abc"}


class TestAssessToolCall:
    def _make_graph(self) -> ToolGraph:
        return TestValidateToolCall()._make_graph()

    def test_read_only_tool_is_allowed(self) -> None:
        tg = self._make_graph()
        assessment = tg.assess_tool_call({"name": "getUser", "arguments": {"user_id": "abc"}})
        assert assessment.decision == ToolCallDecision.ALLOW
        assert assessment.tool_name == "getUser"

    def test_destructive_tool_requires_confirmation(self) -> None:
        tg = self._make_graph()
        assessment = tg.assess_tool_call({"name": "deleteUser", "arguments": {"user_id": "123"}})
        assert assessment.decision == ToolCallDecision.CONFIRM
        assert any("destructive" in reason for reason in assessment.reasons)

    def test_destructive_tool_with_name_correction_is_denied(self) -> None:
        tg = self._make_graph()
        assessment = tg.assess_tool_call({"name": "deleteuser", "arguments": {"user_id": "123"}})
        assert assessment.decision == ToolCallDecision.DENY
        assert any("auto-corrected" in reason for reason in assessment.reasons)

    def test_unknown_tool_is_denied(self) -> None:
        tg = self._make_graph()
        assessment = tg.assess_tool_call({"name": "destroyDatabase", "arguments": {}})
        assert assessment.decision == ToolCallDecision.DENY
        assert any("unknown tool" in reason for reason in assessment.reasons)

    def test_non_idempotent_write_requires_confirmation(self) -> None:
        tg = ToolGraph()
        tg.add_tool(
            {
                "name": "createUser",
                "description": "Create user",
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                },
            }
        )
        assessment = tg.assess_tool_call({"name": "createUser", "arguments": {"name": "son"}})
        assert assessment.decision == ToolCallDecision.CONFIRM
        assert any("non-idempotent" in reason for reason in assessment.reasons)

    def test_policy_can_allow_corrected_non_destructive_call(self) -> None:
        tg = self._make_graph()
        policy = ToolCallPolicy(confirm_on_corrections=False)
        assessment = tg.assess_tool_call(
            {"name": "getuser", "arguments": {"user_id": "abc"}},
            policy=policy,
        )
        assert assessment.decision == ToolCallDecision.ALLOW


# ---------------------------------------------------------------------------
# retrieve_with_scores()
# ---------------------------------------------------------------------------


class TestRetrieveWithScores:
    def test_returns_retrieval_results(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        results = tg.retrieve_with_scores("list pets", top_k=3)
        assert len(results) > 0
        assert all(isinstance(r, RetrievalResult) for r in results)

    def test_scores_are_populated(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        results = tg.retrieve_with_scores("list pets", top_k=3)
        top = results[0]
        assert top.score > 0
        assert top.tool.name is not None
        assert top.confidence in ("high", "medium", "low")

    def test_score_ordering(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        results = tg.retrieve_with_scores("delete pet", top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_consistent_with_retrieve(self) -> None:
        """retrieve_with_scores() should return same tools as retrieve()."""
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        tools = tg.retrieve("find pet by status", top_k=3)
        results = tg.retrieve_with_scores("find pet by status", top_k=3)
        assert [t.name for t in tools] == [r.tool.name for r in results]


# ---------------------------------------------------------------------------
# suggest_next()
# ---------------------------------------------------------------------------


class TestSuggestNext:
    def test_suggests_related_tools(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        suggestions = tg.suggest_next("getPet")
        assert len(suggestions) > 0
        # Should suggest tools in the same domain
        names = [s.tool.name for s in suggestions]
        assert any("pet" in n.lower() or "Pet" in n for n in names)

    def test_history_deprioritizes(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        s1 = tg.suggest_next("getPet")
        s2 = tg.suggest_next("getPet", history=["deletePet"])
        # deletePet should have lower weight when in history
        names_with_history = {s.tool.name: s.weight for s in s2}
        if "deletePet" in names_with_history:
            names_without = {s.tool.name: s.weight for s in s1}
            if "deletePet" in names_without:
                assert names_with_history["deletePet"] <= names_without["deletePet"]

    def test_unknown_tool_returns_empty(self) -> None:
        tg = ToolGraph()
        tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
        assert tg.suggest_next("nonExistentTool") == []


# ---------------------------------------------------------------------------
# Korean intent normalization
# ---------------------------------------------------------------------------


class TestKoreanIntentNormalization:
    def test_postposition_removal(self) -> None:
        from graph_tool_call.retrieval.intent import classify_intent

        # "사용자를 삭제" → should detect delete intent
        intent = classify_intent("사용자를 삭제")
        assert intent.delete_intent > 0

    def test_verb_ending_removal(self) -> None:
        from graph_tool_call.retrieval.intent import classify_intent

        # "목록을 조회해줘" → should detect read intent
        intent = classify_intent("목록을 조회해줘")
        assert intent.read_intent > 0

    def test_korean_colloquial(self) -> None:
        from graph_tool_call.retrieval.intent import classify_intent

        # "사용자 지워" → should detect delete intent
        intent = classify_intent("사용자 지워")
        assert intent.delete_intent > 0

    def test_korean_write_intent(self) -> None:
        from graph_tool_call.retrieval.intent import classify_intent

        # "사용자 만들어" → should detect write intent
        intent = classify_intent("사용자 만들어")
        assert intent.write_intent > 0

    def test_mixed_korean_english(self) -> None:
        from graph_tool_call.retrieval.intent import classify_intent

        # "user 삭제해주세요" → should detect delete intent
        intent = classify_intent("user 삭제해주세요")
        assert intent.delete_intent > 0
