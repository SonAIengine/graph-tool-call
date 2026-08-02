"""LangChain v1 middleware for per-turn graph-based tool selection."""

from __future__ import annotations

import logging
from typing import Any

from graph_tool_call.langchain.agent import _extract_query_from_langchain_messages
from graph_tool_call.toolkit import GraphToolkit, _extract_name

logger = logging.getLogger("graph-tool-call.langchain.middleware")


def create_tool_selection_middleware(
    tools: list[Any],
    *,
    graph: Any | None = None,
    top_k: int = 5,
) -> Any:
    """Return LangChain v1 middleware that filters pre-registered tools.

    Pass the returned middleware to ``langchain.agents.create_agent`` while
    keeping the complete tool list on the agent.  The middleware narrows the
    tools before every model call and never re-introduces a tool removed by an
    earlier permission, feature-flag, or runtime-context middleware.
    """
    try:
        from langchain.agents.middleware import AgentMiddleware
    except ImportError:
        raise ImportError(
            'LangChain v1 is required. Install with: pip install "graph-tool-call[langchain]"'
        ) from None

    toolkit = GraphToolkit(tools, graph=graph, top_k=top_k)

    class GraphToolSelectionMiddleware(AgentMiddleware):
        """Dynamically expose only graph-retrieved tools to the model."""

        def _select(self, request: Any) -> Any:
            messages = getattr(request, "messages", None)
            if messages is None:
                state = getattr(request, "state", {}) or {}
                messages = state.get("messages", [])

            query = _extract_query_from_langchain_messages(list(messages or []))
            if not query:
                return request

            selected = toolkit.get_tools(query, top_k=top_k)
            available = list(getattr(request, "tools", []) or [])
            available_by_name = {_extract_name(tool): tool for tool in available}
            filtered = [
                available_by_name[name]
                for tool in selected
                if (name := _extract_name(tool)) in available_by_name
            ]

            if not filtered:
                logger.debug("No LangChain tools matched query; preserving current tools")
                return request

            logger.debug(
                "Filtered LangChain tools %d -> %d for query: %s",
                len(available),
                len(filtered),
                query[:50],
            )
            return request.override(tools=filtered)

        def wrap_model_call(self, request: Any, handler: Any) -> Any:
            return handler(self._select(request))

        async def awrap_model_call(self, request: Any, handler: Any) -> Any:
            return await handler(self._select(request))

    return GraphToolSelectionMiddleware()
