import sys
from types import SimpleNamespace

import pytest

from benchmarks.paper_baselines import (
    DEFAULT_CONTEXT_TOKENIZER,
    DEFAULT_CONTEXT_TOKENIZER_REVISION,
    HuggingFaceTokenCounter,
    apply_ranked_token_budget,
    serialize_model_facing_schemas,
)
from graph_tool_call.core.tool import ToolParameter, ToolSchema


class CharacterTokenCounter:
    def count(self, text: str) -> int:
        return len(text)


def _tools() -> dict[str, ToolSchema]:
    return {
        "first": ToolSchema(
            name="first",
            description="First complete schema.",
            parameters=[ToolParameter(name="id", required=True)],
        ),
        "second": ToolSchema(
            name="second",
            description="Second complete schema is deliberately longer.",
            parameters=[ToolParameter(name="query")],
        ),
        "third": ToolSchema(name="third"),
    }


def test_model_facing_schema_serialization_is_canonical():
    tools = _tools()

    first = serialize_model_facing_schemas(["first", "second"], tools)
    repeated = serialize_model_facing_schemas(["first", "second"], dict(reversed(tools.items())))

    assert first == repeated
    assert "\n" not in first
    assert first.startswith('[{"description":"First complete schema."')
    assert '"metadata"' not in first


def test_token_budget_keeps_the_longest_complete_ranked_prefix():
    tools = _tools()
    counter = CharacterTokenCounter()
    first_only_budget = counter.count(serialize_model_facing_schemas(["first"], tools))

    selection = apply_ranked_token_budget(
        ["first", "second", "third"],
        tools,
        token_counter=counter,
        token_budget=first_only_budget,
    )

    assert selection.retrieved == ["first"]
    assert selection.schema_tokens == first_only_budget
    assert selection.truncated is True
    assert selection.truncated_at == "second"
    assert selection.considered_candidate_count == 2
    assert selection.token_budget_utilization == 1.0


def test_token_budget_does_not_skip_an_oversized_candidate():
    tools = _tools()
    counter = CharacterTokenCounter()
    third_only_budget = counter.count(serialize_model_facing_schemas(["third"], tools))

    selection = apply_ranked_token_budget(
        ["second", "third"],
        tools,
        token_counter=counter,
        token_budget=third_only_budget,
    )

    assert selection.retrieved == []
    assert selection.truncated_at == "second"
    assert selection.considered_candidate_count == 1


def test_token_budget_preserves_all_candidates_when_they_fit():
    tools = _tools()
    counter = CharacterTokenCounter()
    all_names = ["first", "second", "third"]
    complete_budget = counter.count(serialize_model_facing_schemas(all_names, tools))

    selection = apply_ranked_token_budget(
        all_names,
        tools,
        token_counter=counter,
        token_budget=complete_budget,
    )

    assert selection.retrieved == all_names
    assert selection.schema_tokens == complete_budget
    assert selection.truncated is False
    assert selection.truncated_at == ""
    assert selection.considered_candidate_count == 3


def test_empty_ranking_still_accounts_for_the_serialized_catalog():
    counter = CharacterTokenCounter()

    selection = apply_ranked_token_budget(
        [],
        {},
        token_counter=counter,
        token_budget=2,
    )

    assert selection.retrieved == []
    assert selection.schema_tokens == 2
    assert selection.token_budget_utilization == 1.0
    assert selection.truncated is False


def test_token_budget_rejects_invalid_or_impossible_limits():
    tools = _tools()
    counter = CharacterTokenCounter()

    with pytest.raises(ValueError, match="greater than zero"):
        apply_ranked_token_budget(
            ["first"],
            tools,
            token_counter=counter,
            token_budget=0,
        )
    with pytest.raises(ValueError, match="empty catalog"):
        apply_ranked_token_budget(
            ["first"],
            tools,
            token_counter=counter,
            token_budget=1,
        )


def test_huggingface_counter_pins_revision_and_disables_special_tokens(monkeypatch):
    calls = {}

    class FakeTokenizer:
        def encode(self, text, **kwargs):
            calls["encode"] = {"text": text, **kwargs}
            return [1, 2, 3]

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(name, **kwargs):
            calls["load"] = {"name": name, **kwargs}
            return FakeTokenizer()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=FakeAutoTokenizer),
    )
    counter = HuggingFaceTokenCounter(
        name=DEFAULT_CONTEXT_TOKENIZER,
        revision=DEFAULT_CONTEXT_TOKENIZER_REVISION,
    )

    assert counter.count("catalog") == 3
    assert counter.count("catalog") == 3
    assert calls["load"] == {
        "name": "Qwen/Qwen3-4B",
        "revision": "1cfa9a7208912126459214e8b04321603b3df60c",
        "trust_remote_code": False,
    }
    assert calls["encode"] == {
        "text": "catalog",
        "add_special_tokens": False,
    }
