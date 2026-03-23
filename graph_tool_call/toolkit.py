"""Toolkit: wrap existing tools with graph-based filtering.

Provides :func:`filter_tools` for one-shot filtering and
:class:`GraphToolkit` for reusable tool management with retrieval.

Accepts any tool format:
- LangChain ``BaseTool`` (``@tool``, ``StructuredTool``, etc.)
- OpenAI function dict (``{"type": "function", "function": {"name": ...}}``)
- Anthropic tool dict (``{"name": ..., "input_schema": ...}``)
- MCP tool dict (``{"name": ..., "inputSchema": ...}``)
- Python callable with type hints

Usage::

    from graph_tool_call.langchain import filter_tools, GraphToolkit

    # One-shot: filter tools by query
    filtered = filter_tools(all_tools, "cancel order", top_k=5)

    # Reusable: wrap once, filter many times
    toolkit = GraphToolkit(tools=all_tools, top_k=5)
    filtered = toolkit.get_tools("cancel order")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("graph-tool-call.langchain")


def _extract_name(tool: Any) -> str:
    """Extract tool name from any supported format."""
    # Object with .name attribute (LangChain BaseTool, ToolSchema, etc.)
    if hasattr(tool, "name"):
        return tool.name

    # Dict formats
    if isinstance(tool, dict):
        # OpenAI: {"type": "function", "function": {"name": ...}}
        if "function" in tool:
            return tool["function"].get("name", "")
        # MCP / Anthropic: {"name": ...}
        if "name" in tool:
            return tool["name"]

    # Callable (Python function)
    if callable(tool):
        return getattr(tool, "__name__", "")

    return ""


def _ingest_tools(graph: Any, tools: list[Any]) -> None:
    """Ingest tools into a ToolGraph, auto-detecting format."""
    from graph_tool_call.core.tool import parse_tool

    callables = []
    for tool in tools:
        if callable(tool) and not hasattr(tool, "name") and not isinstance(tool, dict):
            callables.append(tool)
        else:
            graph.add_tool(parse_tool(tool))

    if callables:
        graph.ingest_functions(callables)


def filter_tools(
    tools: list[Any],
    query: str,
    *,
    top_k: int = 5,
    graph: Any | None = None,
) -> list[Any]:
    """Filter tools by relevance to *query*.

    Parameters
    ----------
    tools:
        List of tools in any format — LangChain ``BaseTool``, OpenAI function
        dicts, MCP tool dicts, Anthropic tool dicts, or Python callables.
    query:
        Natural-language query to match tools against.
    top_k:
        Maximum number of tools to return (default: 5).
    graph:
        Optional pre-built ``ToolGraph``. If *None*, a temporary graph is
        built from *tools* on the fly.

    Returns
    -------
    list
        Subset of *tools* ranked by relevance. Original tool objects are
        preserved (not copies), so they remain callable by the agent.
    """
    from graph_tool_call import ToolGraph

    if graph is None:
        graph = ToolGraph()

    # Index by name for fast lookup
    tool_map: dict[str, Any] = {}
    for t in tools:
        name = _extract_name(t)
        if name:
            tool_map[name] = t

    # Ingest if not already present
    existing = set(graph.tools.keys())
    if not existing.intersection(tool_map.keys()):
        _ingest_tools(graph, tools)

    results = graph.retrieve(query, top_k=top_k)
    result_names = [r.name for r in results]

    filtered = [tool_map[name] for name in result_names if name in tool_map]

    if filtered:
        logger.debug(
            "Filtered %d → %d tools for query: %s",
            len(tools),
            len(filtered),
            query[:50],
        )
        return filtered

    logger.debug("Retrieval returned no matches, returning all %d tools", len(tools))
    return list(tools)


class GraphToolkit:
    """Wraps a list of tools with graph-based retrieval.

    Build once from existing tools, then call :meth:`get_tools` per query.

    Parameters
    ----------
    tools:
        List of tools in any format — LangChain ``BaseTool``, OpenAI function
        dicts, MCP tool dicts, Anthropic tool dicts, or Python callables.
    top_k:
        Default number of tools to return per query.
    graph:
        Optional pre-built ``ToolGraph``. If *None*, one is built from *tools*.
    """

    def __init__(
        self,
        tools: list[Any],
        *,
        top_k: int = 5,
        graph: Any | None = None,
    ) -> None:
        from graph_tool_call import ToolGraph

        self._tools: dict[str, Any] = {}
        for t in tools:
            name = _extract_name(t)
            if name:
                self._tools[name] = t

        self._top_k = top_k

        if graph is not None:
            self._graph: ToolGraph = graph
        else:
            self._graph = ToolGraph()

        # Ingest tools into graph
        existing = set(self._graph.tools.keys())
        if not existing.intersection(self._tools.keys()):
            _ingest_tools(self._graph, tools)

    @property
    def graph(self) -> Any:
        """Underlying ``ToolGraph`` instance."""
        return self._graph

    @property
    def all_tools(self) -> list[Any]:
        """All registered tools."""
        return list(self._tools.values())

    def get_tools(self, query: str, *, top_k: int | None = None) -> list[Any]:
        """Return tools relevant to *query*.

        Parameters
        ----------
        query:
            Natural-language query.
        top_k:
            Override the default top_k for this call.

        Returns
        -------
        list
            Filtered tools, ordered by relevance. Original objects preserved.
        """
        k = top_k if top_k is not None else self._top_k
        results = self._graph.retrieve(query, top_k=k)
        result_names = [r.name for r in results]

        filtered = [self._tools[name] for name in result_names if name in self._tools]
        return filtered if filtered else self.all_tools
