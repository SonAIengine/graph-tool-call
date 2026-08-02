"""Tests for the LangChain v1 dynamic tool-selection middleware."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

pytest.importorskip("langchain", reason="LangChain v1 required")

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from graph_tool_call.langchain import create_tool_selection_middleware


@tool
def get_user(user_id: str) -> str:
    """Get one user account by ID."""
    return user_id


@tool
def delete_user(user_id: str) -> str:
    """Delete a user account permanently."""
    return user_id


@tool
def list_orders(customer_id: str) -> str:
    """List orders for a customer."""
    return customer_id


@dataclass
class FakeRequest:
    messages: list[Any]
    tools: list[Any]

    def override(self, **changes: Any) -> FakeRequest:
        return replace(self, **changes)


def test_middleware_filters_tools_for_model_call():
    tools = [get_user, delete_user, list_orders]
    middleware = create_tool_selection_middleware(tools, top_k=1)
    request = FakeRequest(
        messages=[HumanMessage(content="delete a user account")],
        tools=tools,
    )

    seen = {}

    def handler(updated):
        seen["tools"] = updated.tools
        return "ok"

    assert middleware.wrap_model_call(request, handler) == "ok"
    assert [item.name for item in seen["tools"]] == ["delete_user"]


def test_middleware_does_not_reintroduce_permission_filtered_tools():
    tools = [get_user, delete_user, list_orders]
    middleware = create_tool_selection_middleware(tools, top_k=2)
    request = FakeRequest(
        messages=[HumanMessage(content="delete a user account")],
        tools=[get_user, list_orders],
    )

    seen = {}

    def handler(updated):
        seen["tools"] = updated.tools
        return "ok"

    middleware.wrap_model_call(request, handler)
    assert delete_user not in seen["tools"]


def test_middleware_preserves_retrieval_rank_over_registration_order():
    tools = [get_user, delete_user, list_orders]
    middleware = create_tool_selection_middleware(tools, top_k=2)
    request = FakeRequest(
        messages=[HumanMessage(content="delete a user account")],
        tools=tools,
    )

    selected_names = middleware.wrap_model_call(
        request,
        lambda updated: [item.name for item in updated.tools],
    )

    assert selected_names[0] == "delete_user"


@pytest.mark.asyncio
async def test_async_middleware_uses_same_selection():
    tools = [get_user, delete_user, list_orders]
    middleware = create_tool_selection_middleware(tools, top_k=1)
    request = FakeRequest(
        messages=[HumanMessage(content="list customer orders")],
        tools=tools,
    )

    async def handler(updated):
        return [item.name for item in updated.tools]

    assert await middleware.awrap_model_call(request, handler) == ["list_orders"]
