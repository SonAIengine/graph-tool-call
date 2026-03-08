"""Ingest MCP (Model Context Protocol) tool lists into ToolSchema instances."""

from __future__ import annotations

from typing import Any

from graph_tool_call.core.tool import ToolSchema, normalize_tool, parse_mcp_tool


def ingest_mcp_tools(
    tools: list[dict[str, Any]],
    *,
    server_name: str | None = None,
) -> list[ToolSchema]:
    """Parse a list of MCP tool dicts into ToolSchema instances.

    Parameters
    ----------
    tools:
        List of MCP tool dicts with ``name``, ``description``, ``inputSchema``,
        and optional ``annotations``.
    server_name:
        Optional server name to store in metadata and use as tag.

    Returns
    -------
    list[ToolSchema]
        Parsed tool schemas with MCP annotations preserved.
    """
    result: list[ToolSchema] = []
    for tool_dict in tools:
        schema = parse_mcp_tool(tool_dict)
        schema.metadata["source"] = "mcp"
        if server_name:
            schema.metadata["mcp_server"] = server_name
            if server_name not in schema.tags:
                schema.tags.append(server_name)
        normalize_tool(schema)
        result.append(schema)
    return result
