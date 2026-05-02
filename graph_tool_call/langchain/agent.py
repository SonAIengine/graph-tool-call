"""LangChain/LangGraph agent with automatic per-turn tool filtering.

Wraps ``create_react_agent`` so the LLM only sees relevant tools each turn,
cutting token usage dramatically on large tool sets.

Two query modes:

- ``query_mode="message"`` (default): uses the latest user message as-is
  for retrieval. Fast, no extra LLM call.
- ``query_mode="llm"``: asks the LLM to generate a search query from the
  full conversation context. Better for multi-turn ("그거 취소해줘") and
  ambiguous queries, at the cost of one extra LLM call per turn.

Usage::

    from graph_tool_call.langchain import create_agent

    # Fast mode (default)
    agent = create_agent(llm, tools=all_200_tools, top_k=5)

    # LLM query mode (better for multi-turn conversations)
    agent = create_agent(llm, tools=all_200_tools, top_k=5, query_mode="llm")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

logger = logging.getLogger("graph-tool-call.langchain")

_QUERY_GEN_SYSTEM = """\
You are a tool search query generator. Given a conversation, write a short \
English search query (3-8 words) that describes what tools the user needs.

Rules:
- Output ONLY the search query, nothing else.
- Use English keywords even if the conversation is in another language.
- Focus on the action (cancel, create, send, delete, get, list, etc.).
- Resolve pronouns from context ("that order" → "cancel order #123").
- If the user's intent is unclear, describe the most likely action.

Examples:
- Conversation: "아까 그 주문 취소해줘" → "cancel order"
- Conversation: "Send it to John" (after discussing emails) → "send email"
- Conversation: "How's the weather?" → "get weather"
- Conversation: "Refund that and notify the customer" → "process refund send notification"\
"""


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


def _build_conversation_summary(messages: list[Any], max_turns: int = 6) -> str:
    """Build a compact conversation summary for the query-gen LLM."""
    lines = []
    count = 0
    for msg in reversed(messages):
        if count >= max_turns:
            break
        role = None
        content = None

        if hasattr(msg, "type") and hasattr(msg, "content"):
            role = msg.type
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
        elif isinstance(msg, (list, tuple)) and len(msg) >= 2:
            role = str(msg[0])
            content = str(msg[1])

        if role and content:
            lines.append(f"{role}: {content[:200]}")
            count += 1

    lines.reverse()
    return "\n".join(lines)


def _generate_query_with_llm(
    model: Any,
    messages: list[Any],
    tool_names: list[str],
) -> str | None:
    """Ask the LLM to generate a tool search query from conversation context."""
    from langchain_core.messages import HumanMessage, SystemMessage

    conversation = _build_conversation_summary(messages)
    if not conversation:
        return None

    # Include a sample of tool names to help the LLM understand the domain
    sample_tools = ", ".join(tool_names[:20])
    user_prompt = (
        f"Available tools include: {sample_tools}\n\nConversation:\n{conversation}\n\nSearch query:"
    )

    try:
        # Use the model without tools bound (raw LLM call)
        base_model = model
        if hasattr(model, "bound_tools"):
            # If model has tools bound, get the underlying model
            base_model = model
        response = base_model.invoke(
            [
                SystemMessage(content=_QUERY_GEN_SYSTEM),
                HumanMessage(content=user_prompt),
            ]
        )
        query = response.content.strip().strip('"').strip("'")
        if query:
            logger.debug("LLM-generated query: %s", query)
            return query
    except Exception as e:
        logger.warning("Query generation failed, falling back to message: %s", e)

    return None


def create_agent(
    model: Any,
    tools: list[Any],
    *,
    top_k: int = 5,
    graph: Any | None = None,
    query_mode: Literal["message", "llm"] = "message",
    query_model: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Create a ReAct agent with automatic per-turn tool filtering.

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
    query_mode:
        - ``"message"`` (default): use latest user message as search query.
          Fast, no extra LLM call.
        - ``"llm"``: ask the LLM to generate a search query from conversation
          context. Better for multi-turn and ambiguous queries.
    query_model:
        Optional separate model for query generation (only used when
        ``query_mode="llm"``). Use a small/fast model to save cost.
        If *None*, uses the same *model*.
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
            "langgraph is required for create_agent(). Install with: pip install langgraph"
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

    tool_names = list(tool_map.keys())
    _query_model = query_model or model

    # Dynamic model factory: called each turn with (state, runtime)
    def model_factory(state: dict[str, Any], runtime: Any) -> Any:
        messages = state.get("messages", [])

        query = None
        if query_mode == "llm":
            query = _generate_query_with_llm(_query_model, messages, tool_names)

        # Fallback to raw user message
        if not query:
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
