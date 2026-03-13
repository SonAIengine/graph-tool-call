"""Tests for SDK middleware (OpenAI / Anthropic patching)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from graph_tool_call import ToolGraph
from graph_tool_call.middleware import (
    _extract_query_from_anthropic_messages,
    _extract_query_from_openai_messages,
    patch_anthropic,
    patch_openai,
    unpatch_anthropic,
    unpatch_openai,
)


def _make_openai_client(create_fn=None):
    """Build a fake OpenAI client using SimpleNamespace (no auto-attr like MagicMock)."""
    completions = SimpleNamespace(create=create_fn or (lambda **kw: MagicMock()))
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def _make_anthropic_client(create_fn=None):
    """Build a fake Anthropic client using SimpleNamespace."""
    messages = SimpleNamespace(create=create_fn or (lambda **kw: MagicMock()))
    return SimpleNamespace(messages=messages)

# --- Test data ---

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getUser",
            "description": "Get user by ID",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "User ID"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteUser",
            "description": "Delete a user account",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "User ID"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listOrders",
            "description": "List orders for a customer",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createPayment",
            "description": "Process a payment",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
            },
        },
    },
]

ANTHROPIC_TOOLS = [
    {
        "name": "getUser",
        "description": "Get user by ID",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "User ID"}},
            "required": ["id"],
        },
    },
    {
        "name": "deleteUser",
        "description": "Delete a user account",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "User ID"}},
            "required": ["id"],
        },
    },
    {
        "name": "listOrders",
        "description": "List orders for a customer",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
        },
    },
    {
        "name": "createPayment",
        "description": "Process a payment",
        "input_schema": {
            "type": "object",
            "properties": {"amount": {"type": "number"}},
        },
    },
]


@pytest.fixture()
def tool_graph():
    tg = ToolGraph()
    tg.add_tools(OPENAI_TOOLS)
    return tg


# --- Message extraction tests ---


class TestExtractQuery:
    def test_openai_simple_string(self):
        msgs = [{"role": "user", "content": "delete user"}]
        assert _extract_query_from_openai_messages(msgs) == "delete user"

    def test_openai_multipart_content(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "find"},
                    {"type": "text", "text": "user"},
                ],
            }
        ]
        assert _extract_query_from_openai_messages(msgs) == "find user"

    def test_openai_picks_last_user_message(self):
        msgs = [
            {"role": "user", "content": "old query"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "new query"},
        ]
        assert _extract_query_from_openai_messages(msgs) == "new query"

    def test_openai_no_user_message(self):
        msgs = [{"role": "system", "content": "you are helpful"}]
        assert _extract_query_from_openai_messages(msgs) is None

    def test_anthropic_simple_string(self):
        msgs = [{"role": "user", "content": "delete user"}]
        assert _extract_query_from_anthropic_messages(msgs) == "delete user"

    def test_anthropic_content_blocks(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "manage orders"}],
            }
        ]
        assert _extract_query_from_anthropic_messages(msgs) == "manage orders"


# --- Patch/unpatch tests ---


class TestPatchOpenAI:
    def test_patch_and_unpatch(self, tool_graph):
        client = _make_openai_client()
        original_create = client.chat.completions.create

        patch_openai(client, graph=tool_graph)
        assert client.chat.completions.create is not original_create

        unpatch_openai(client)
        assert client.chat.completions.create is original_create

    def test_patched_filters_tools(self, tool_graph):
        call_record = {}

        def fake_create(*args, **kwargs):
            call_record["tools"] = kwargs.get("tools", [])
            return MagicMock()

        client = _make_openai_client(fake_create)
        patch_openai(client, graph=tool_graph, top_k=2)

        client.chat.completions.create(
            model="gpt-4o",
            tools=OPENAI_TOOLS,
            messages=[{"role": "user", "content": "delete a user account"}],
        )

        # Should have filtered to top_k=2
        assert len(call_record["tools"]) <= 2

    def test_skips_small_tool_list(self, tool_graph):
        call_record = {}

        def fake_create(*args, **kwargs):
            call_record["tools"] = kwargs.get("tools", [])
            return MagicMock()

        client = _make_openai_client(fake_create)
        patch_openai(client, graph=tool_graph, min_tools=10)

        small_tools = OPENAI_TOOLS[:2]
        client.chat.completions.create(
            model="gpt-4o",
            tools=small_tools,
            messages=[{"role": "user", "content": "delete user"}],
        )

        # Should pass through unfiltered (2 < min_tools=10)
        assert len(call_record["tools"]) == 2

    def test_no_tools_passes_through(self, tool_graph):
        call_record = {}

        def fake_create(*args, **kwargs):
            call_record["kwargs"] = kwargs
            return MagicMock()

        client = _make_openai_client(fake_create)
        patch_openai(client, graph=tool_graph)

        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert "tools" not in call_record["kwargs"]


class TestPatchAnthropic:
    def test_patch_and_unpatch(self, tool_graph):
        client = _make_anthropic_client()
        original_create = client.messages.create

        patch_anthropic(client, graph=tool_graph)
        assert client.messages.create is not original_create

        unpatch_anthropic(client)
        assert client.messages.create is original_create

    def test_patched_filters_tools(self, tool_graph):
        call_record = {}

        def fake_create(*args, **kwargs):
            call_record["tools"] = kwargs.get("tools", [])
            return MagicMock()

        client = _make_anthropic_client(fake_create)
        patch_anthropic(client, graph=tool_graph, top_k=2)

        client.messages.create(
            model="claude-sonnet-4-20250514",
            tools=ANTHROPIC_TOOLS,
            messages=[{"role": "user", "content": "get user information"}],
        )

        assert len(call_record["tools"]) <= 2

    def test_double_patch_warns(self, tool_graph):
        client = _make_anthropic_client()
        patch_anthropic(client, graph=tool_graph)
        # Second patch should warn but not crash
        patch_anthropic(client, graph=tool_graph)
