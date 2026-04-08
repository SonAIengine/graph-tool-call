"""Tests for graph_tool_call.langchain.agent (create_agent)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("langgraph", reason="langgraph required")
pytest.importorskip("langchain_core", reason="langchain-core required")


def test_extract_query_from_human_message():
    from langchain_core.messages import AIMessage, HumanMessage

    from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages

    msgs = [
        HumanMessage(content="cancel my order"),
        AIMessage(content="sure"),
    ]
    assert _extract_query_from_langchain_messages(msgs) == "cancel my order"


def test_extract_query_from_tuple():
    from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages

    msgs = [("user", "delete a file")]
    assert _extract_query_from_langchain_messages(msgs) == "delete a file"


def test_extract_query_picks_latest_human():
    from langchain_core.messages import AIMessage, HumanMessage

    from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages

    msgs = [
        HumanMessage(content="first question"),
        AIMessage(content="answer"),
        HumanMessage(content="second question"),
    ]
    assert _extract_query_from_langchain_messages(msgs) == "second question"


def test_extract_query_multimodal_content():
    from langchain_core.messages import HumanMessage

    from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages

    msgs = [
        HumanMessage(content=[{"type": "text", "text": "what is this"}]),
    ]
    assert _extract_query_from_langchain_messages(msgs) == "what is this"


def test_extract_query_returns_none_for_empty():
    from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages

    assert _extract_query_from_langchain_messages([]) is None


def test_create_agent_builds_graph_and_calls_create_react_agent():
    """create_agent should build a ToolGraph and pass a model factory."""
    from langchain_core.tools import tool

    @tool
    def get_weather(city: str) -> str:
        """Get weather for a city."""
        return "sunny"

    @tool
    def send_email(to: str, body: str) -> str:
        """Send an email."""
        return "sent"

    @tool
    def cancel_order(order_id: str) -> str:
        """Cancel an existing order."""
        return "cancelled"

    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    with patch("langgraph.prebuilt.create_react_agent") as mock_cra:
        mock_cra.return_value = MagicMock()

        from graph_tool_call.langchain.agent import create_agent

        create_agent(
            mock_model,
            tools=[get_weather, send_email, cancel_order],
            top_k=2,
        )

        # create_react_agent should have been called
        mock_cra.assert_called_once()
        call_kwargs = mock_cra.call_args

        # model arg should be a callable (model factory), not the raw model
        model_arg = call_kwargs[1]["model"] if "model" in call_kwargs[1] else call_kwargs[0][0]
        assert callable(model_arg)

        # tools should be the full list
        tools_arg = call_kwargs[1]["tools"] if "tools" in call_kwargs[1] else call_kwargs[0][1]
        assert len(tools_arg) == 3


def test_model_factory_filters_tools():
    """The model factory should call bind_tools with filtered subset."""
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    @tool
    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return "sunny"

    @tool
    def send_email(to: str, body: str) -> str:
        """Send an email to someone."""
        return "sent"

    @tool
    def cancel_order(order_id: str) -> str:
        """Cancel an existing order."""
        return "cancelled"

    @tool
    def process_refund(order_id: str) -> str:
        """Process a refund for a cancelled order."""
        return "refunded"

    @tool
    def search_users(query: str) -> str:
        """Search for users by name."""
        return "found"

    all_tools = [get_weather, send_email, cancel_order, process_refund, search_users]

    mock_model = MagicMock()
    bound_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=bound_model)

    with patch("langgraph.prebuilt.create_react_agent") as mock_cra:
        mock_cra.return_value = MagicMock()

        from graph_tool_call.langchain.agent import create_agent

        create_agent(mock_model, tools=all_tools, top_k=2)

        # Get the model factory
        model_factory = mock_cra.call_args[1]["model"]

        # Simulate a turn with weather query
        state = {"messages": [HumanMessage(content="what's the weather in Seoul")]}
        runtime = MagicMock()

        model_factory(state, runtime)

        # bind_tools should have been called with a filtered subset
        mock_model.bind_tools.assert_called_once()
        bound_tools = mock_model.bind_tools.call_args[0][0]
        assert len(bound_tools) <= 2
        bound_names = [t.name for t in bound_tools]
        assert "get_weather" in bound_names


def test_model_factory_fallback_on_no_query():
    """With no user message, model factory should bind all tools."""
    from langchain_core.tools import tool

    @tool
    def my_tool(x: str) -> str:
        """A tool."""
        return x

    mock_model = MagicMock()
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    with patch("langgraph.prebuilt.create_react_agent") as mock_cra:
        mock_cra.return_value = MagicMock()

        from graph_tool_call.langchain.agent import create_agent

        create_agent(mock_model, tools=[my_tool], top_k=2)

        model_factory = mock_cra.call_args[1]["model"]
        state = {"messages": []}
        runtime = MagicMock()

        model_factory(state, runtime)

        # Should fallback to all tools
        bound_tools = mock_model.bind_tools.call_args[0][0]
        assert len(bound_tools) == 1


def test_create_agent_import():
    """create_agent should be importable from langchain package."""
    from graph_tool_call.langchain import create_agent

    assert callable(create_agent)
