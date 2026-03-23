"""LangChain/LangGraph agent with automatic per-turn tool filtering.

Wraps ``create_react_agent`` so the LLM only sees relevant tools each turn,
cutting token usage dramatically on large tool sets.

Usage::

    from graph_tool_call.langchain import create_agent

    agent = create_agent(llm, tools=all_200_tools, top_k=5)
    result = agent.invoke({"messages": [("user", "cancel my order")]})
    # LLM saw only ~5 tools instead of 200

This works by passing a dynamic model factory to ``create_react_agent``:
each turn, the latest user message is used to retrieve relevant tools
via ``ToolGraph``, and only those are bound to the model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger("graph-tool-call.langchain")


def _extract_query_from_langchain_messages(messages: list[Any]) -> str | None:
    """Extract the latest user message text from LangChain BaseMessage list."""
    for msg in reversed(messages):
        # LangChain BaseMessage
        if hasattr(msg, "type") and hasattr(msg, "content"):
            if msg.type == "human":
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            texts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            texts.append(part)
                    if texts:
                        return " ".join(texts)

        # Tuple format: ("user", "message")
        if isinstance(msg, (list, tuple)) and len(msg) >= 2:
            if msg[0] in ("user", "human"):
                return str(msg[1])

    return None


def create_agent(
    model: Any,
    tools: list[Any],
    *,
    top_k: int = 5,
    graph: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Create a ReAct agent with automatic per-turn tool filtering.

    Each LLM turn, the latest user message is used to retrieve the ``top_k``
    most relevant tools via ``ToolGraph``. The model only sees (and pays tokens
    for) those tools — not the full list.

    Parameters
    ----------
    model:
        A LangChain ``BaseChatModel`` (e.g. ``ChatOpenAI``, ``ChatAnthropic``).
    tools:
        Full list of tools (LangChain ``BaseTool``, callables, or dicts).
    top_k:
        Number of tools to show the LLM each turn (default: 5).
    graph:
        Optional pre-built ``ToolGraph``. If *None*, one is built from *tools*.
    **kwargs:
        Passed through to ``create_react_agent`` (prompt, checkpointer, etc.).

    Returns
    -------
    CompiledStateGraph
        A LangGraph agent that can be invoked with
        ``agent.invoke({"messages": [...]})``.
    """
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        raise ImportError(
            "langgraph is required for create_agent(). "
            "Install with: pip install langgraph"
        )

    from graph_tool_call import ToolGraph
    from graph_tool_call.toolkit import _extract_name, _ingest_tools

    # Build tool graph
    if graph is None:
        graph = ToolGraph()

    tool_map: dict[str, Any] = {}
    for t in tools:
        name = _extract_name(t)
        if name:
            tool_map[name] = t

    existing = set(graph.tools.keys())
    if not existing.intersection(tool_map.keys()):
        _ingest_tools(graph, tools)

    # Dynamic model factory: called each turn with (state, runtime)
    def model_factory(state: dict[str, Any], runtime: Any) -> Any:
        messages = state.get("messages", [])
        query = _extract_query_from_langchain_messages(messages)

        if query:
            results = graph.retrieve(query, top_k=top_k)
            result_names = [r.name for r in results]
            filtered = [tool_map[n] for n in result_names if n in tool_map]

            if filtered:
                logger.debug(
                    "Turn filter: %d → %d tools for: %s",
                    len(tools),
                    len(filtered),
                    query[:50],
                )
                return model.bind_tools(filtered)

        # Fallback: bind all tools
        return model.bind_tools(tools)

    return create_react_agent(
        model=model_factory,
        tools=tools,
        **kwargs,
    )
