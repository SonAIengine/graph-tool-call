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
    response = client.responses.create(
        model="gpt-4o",
        tools=all_248_tools,   # only ~5 relevant tools actually sent
        input="delete a user",
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


def _extract_query_from_messages(messages: list[dict[str, Any]]) -> str | None:
    """Extract the latest user message text (works with both OpenAI and Anthropic formats)."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    texts.append(part.get("text", ""))
                elif isinstance(part, str):
                    texts.append(part)
            if texts:
                return " ".join(texts)
    return None


def _extract_query_from_openai_input(value: Any) -> str | None:
    """Extract a query from the Responses API ``input`` value."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        direct_texts = [
            row.get("text", "")
            for row in value
            if isinstance(row, dict) and row.get("type") in {"text", "input_text"}
        ]
        if direct_texts:
            return " ".join(text for text in direct_texts if text)
        messages = [row for row in value if isinstance(row, dict)]
        return _extract_query_from_messages(messages)
    return None


def _extract_tool_name(tool: dict[str, Any]) -> str:
    """Extract tool name from OpenAI (function.name) or Anthropic (name) format."""
    if "function" in tool:
        return tool["function"].get("name", "")
    return tool.get("name", "")


def _filter_tools(
    tools: list[dict[str, Any]],
    query: str,
    graph: Any,
    top_k: int,
) -> list[dict[str, Any]]:
    """Filter tools using ToolGraph retrieval (format-agnostic)."""
    from graph_tool_call import ToolGraph

    tg: ToolGraph = graph

    input_tool_map: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = _extract_tool_name(tool)
        if name:
            input_tool_map[name] = tool

    if not set(tg.tools.keys()).intersection(input_tool_map.keys()):
        tg.add_tools(tools)

    results = tg.retrieve(query, top_k=top_k)
    filtered = [input_tool_map[r.name] for r in results if r.name in input_tool_map]
    passthrough = [tool for tool in tools if not _extract_tool_name(tool)]

    if filtered:
        logger.debug(
            "Filtered %d → %d tools for query: %s",
            len(tools),
            len(filtered),
            query[:50],
        )
        return [*passthrough, *filtered]

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

    Both ``client.responses.create`` and the legacy
    ``client.chat.completions.create`` surface are patched when present.

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
    endpoints: list[tuple[Any, str]] = []
    responses = getattr(client, "responses", None)
    if responses is not None and hasattr(responses, "create"):
        endpoints.append((responses, "input"))

    chat = getattr(client, "chat", None)
    completions = getattr(chat, "completions", None)
    if completions is not None and hasattr(completions, "create"):
        endpoints.append((completions, "messages"))

    if not endpoints:
        raise TypeError("OpenAI client must expose responses.create or chat.completions.create")

    patched = 0
    for endpoint, query_key in endpoints:
        if hasattr(endpoint, _ORIGINAL_ATTR):
            continue
        _patch_openai_endpoint(
            endpoint,
            query_key=query_key,
            graph=graph,
            top_k=top_k,
            min_tools=min_tools,
        )
        patched += 1

    if not patched:
        logger.warning("Client already patched — call unpatch_openai() first")


def _patch_openai_endpoint(
    endpoint: Any,
    *,
    query_key: str,
    graph: Any,
    top_k: int,
    min_tools: int,
) -> None:
    original_create = endpoint.create

    @functools.wraps(original_create)
    def patched_create(*args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools")
        query_value = kwargs.get(query_key)

        if tools and query_value is not None and len(tools) >= min_tools:
            if query_key == "input":
                query = _extract_query_from_openai_input(query_value)
            else:
                query = _extract_query_from_messages(query_value)
            if query:
                kwargs["tools"] = _filter_tools(tools, query, graph, top_k)

        return original_create(*args, **kwargs)

    setattr(endpoint, _ORIGINAL_ATTR, original_create)
    endpoint.create = patched_create


def unpatch_openai(client: Any) -> None:
    """Remove the graph-tool-call patch from an OpenAI client."""
    endpoints = []
    responses = getattr(client, "responses", None)
    if responses is not None:
        endpoints.append(responses)
    chat = getattr(client, "chat", None)
    completions = getattr(chat, "completions", None)
    if completions is not None:
        endpoints.append(completions)

    for endpoint in endpoints:
        original = getattr(endpoint, _ORIGINAL_ATTR, None)
        if original is not None:
            endpoint.create = original
            delattr(endpoint, _ORIGINAL_ATTR)


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
            query = _extract_query_from_messages(messages)
            if query:
                kwargs["tools"] = _filter_tools(tools, query, graph, top_k)

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
