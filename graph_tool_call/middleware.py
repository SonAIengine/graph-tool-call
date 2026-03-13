"""SDK middleware: auto-filter tools for OpenAI / Anthropic clients.

Monkey-patches the SDK create() method to automatically filter tools
using graph-tool-call retrieval, reducing token usage dramatically.

Usage::

    from graph_tool_call import ToolGraph
    from graph_tool_call.middleware import patch_openai, patch_anthropic

    tg = ToolGraph.from_url("https://api.example.com/openapi.json")

    # OpenAI
    from openai import OpenAI
    client = OpenAI()
    patch_openai(client, graph=tg)
    # Now all calls auto-filter tools based on the user message
    response = client.chat.completions.create(
        model="gpt-4o",
        tools=all_248_tools,   # only ~5 relevant tools actually sent
        messages=[{"role": "user", "content": "delete a user"}],
    )

    # Anthropic
    from anthropic import Anthropic
    client = Anthropic()
    patch_anthropic(client, graph=tg)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        tools=all_tools,       # auto-filtered
        messages=[{"role": "user", "content": "delete a user"}],
    )

    # Undo
    unpatch_openai(client)
    unpatch_anthropic(client)
"""

from __future__ import annotations

import functools
import logging
from typing import Any

logger = logging.getLogger("graph-tool-call.middleware")

_ORIGINAL_ATTR = "_gtc_original_create"


def _extract_query_from_openai_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract the latest user message text from OpenAI-format messages."""
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            # content can be a list of parts
            if isinstance(content, list):
                texts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        texts.append(part)
                if texts:
                    return " ".join(texts)
    return None


def _extract_query_from_anthropic_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract the latest user message text from Anthropic-format messages."""
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                if texts:
                    return " ".join(texts)
    return None


def _filter_tools_openai(
    tools: list[dict[str, Any]],
    query: str,
    graph: Any,
    top_k: int,
) -> list[dict[str, Any]]:
    """Filter OpenAI-format tools using ToolGraph retrieval."""
    from graph_tool_call import ToolGraph

    tg: ToolGraph = graph

    # Build a temporary graph if not already containing these tools
    tool_names_in_graph = set(tg.tools.keys())

    # Extract names from the tool list
    input_tool_map: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if "function" in tool:
            name = tool["function"].get("name", "")
        else:
            name = tool.get("name", "")
        if name:
            input_tool_map[name] = tool

    # If the graph doesn't have these tools, add them temporarily
    if not tool_names_in_graph.intersection(input_tool_map.keys()):
        tg.add_tools(tools)

    # Retrieve relevant tools
    results = tg.retrieve(query, top_k=top_k)
    result_names = {r.name for r in results}

    # Filter original tool dicts to only include retrieved ones
    filtered = [t for name, t in input_tool_map.items() if name in result_names]

    if filtered:
        logger.debug(
            "Filtered %d → %d tools for query: %s",
            len(tools),
            len(filtered),
            query[:50],
        )
        return filtered

    # Fallback: if retrieval returned nothing, pass all tools
    logger.debug("Retrieval returned no results, passing all %d tools", len(tools))
    return tools


def _filter_tools_anthropic(
    tools: list[dict[str, Any]],
    query: str,
    graph: Any,
    top_k: int,
) -> list[dict[str, Any]]:
    """Filter Anthropic-format tools using ToolGraph retrieval."""
    from graph_tool_call import ToolGraph

    tg: ToolGraph = graph

    tool_names_in_graph = set(tg.tools.keys())

    input_tool_map: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = tool.get("name", "")
        if name:
            input_tool_map[name] = tool

    if not tool_names_in_graph.intersection(input_tool_map.keys()):
        tg.add_tools(tools)

    results = tg.retrieve(query, top_k=top_k)
    result_names = {r.name for r in results}

    filtered = [t for name, t in input_tool_map.items() if name in result_names]

    if filtered:
        logger.debug(
            "Filtered %d → %d tools for query: %s",
            len(tools),
            len(filtered),
            query[:50],
        )
        return filtered

    logger.debug("Retrieval returned no results, passing all %d tools", len(tools))
    return tools


# ---------------------------------------------------------------------------
# OpenAI patch
# ---------------------------------------------------------------------------


def patch_openai(
    client: Any,
    *,
    graph: Any,
    top_k: int = 5,
    min_tools: int = 3,
) -> None:
    """Patch an OpenAI client to auto-filter tools via graph-tool-call.

    Parameters
    ----------
    client:
        An ``openai.OpenAI`` or ``openai.AsyncOpenAI`` instance.
    graph:
        A ``ToolGraph`` instance (pre-loaded with tools, or tools will be
        added automatically from the first call's tool list).
    top_k:
        Maximum number of tools to pass through (default: 5).
    min_tools:
        Skip filtering if tool list has fewer than this many tools (default: 3).
    """
    completions = client.chat.completions

    if hasattr(completions, _ORIGINAL_ATTR):
        logger.warning("Client already patched — call unpatch_openai() first")
        return

    original_create = completions.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools")
        messages = kwargs.get("messages")

        if tools and messages and len(tools) >= min_tools:
            query = _extract_query_from_openai_messages(messages)
            if query:
                kwargs["tools"] = _filter_tools_openai(tools, query, graph, top_k)

        return original_create(*args, **kwargs)

    setattr(completions, _ORIGINAL_ATTR, original_create)
    completions.create = patched_create


def unpatch_openai(client: Any) -> None:
    """Remove the graph-tool-call patch from an OpenAI client."""
    completions = client.chat.completions
    original = getattr(completions, _ORIGINAL_ATTR, None)
    if original is not None:
        completions.create = original
        delattr(completions, _ORIGINAL_ATTR)


# ---------------------------------------------------------------------------
# Anthropic patch
# ---------------------------------------------------------------------------


def patch_anthropic(
    client: Any,
    *,
    graph: Any,
    top_k: int = 5,
    min_tools: int = 3,
) -> None:
    """Patch an Anthropic client to auto-filter tools via graph-tool-call.

    Parameters
    ----------
    client:
        An ``anthropic.Anthropic`` or ``anthropic.AsyncAnthropic`` instance.
    graph:
        A ``ToolGraph`` instance.
    top_k:
        Maximum number of tools to pass through (default: 5).
    min_tools:
        Skip filtering if tool list has fewer than this many tools (default: 3).
    """
    messages_api = client.messages

    if hasattr(messages_api, _ORIGINAL_ATTR):
        logger.warning("Client already patched — call unpatch_anthropic() first")
        return

    original_create = messages_api.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools")
        messages = kwargs.get("messages")

        if tools and messages and len(tools) >= min_tools:
            query = _extract_query_from_anthropic_messages(messages)
            if query:
                kwargs["tools"] = _filter_tools_anthropic(tools, query, graph, top_k)

        return original_create(*args, **kwargs)

    setattr(messages_api, _ORIGINAL_ATTR, original_create)
    messages_api.create = patched_create


def unpatch_anthropic(client: Any) -> None:
    """Remove the graph-tool-call patch from an Anthropic client."""
    messages_api = client.messages
    original = getattr(messages_api, _ORIGINAL_ATTR, None)
    if original is not None:
        messages_api.create = original
        delattr(messages_api, _ORIGINAL_ATTR)
