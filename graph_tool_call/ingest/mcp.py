"""Ingest MCP (Model Context Protocol) tool lists into ToolSchema instances."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from graph_tool_call.core.tool import ToolSchema, normalize_tool, parse_mcp_tool
from graph_tool_call.net import post_json


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


def fetch_mcp_tools(
    server_url: str,
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch MCP tools from an HTTP JSON-RPC endpoint via ``tools/list``."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    text = post_json(
        server_url,
        payload,
        timeout=timeout,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        msg = f"Invalid JSON from MCP server: {server_url}"
        raise ValueError(msg) from None

    if isinstance(data, dict) and "error" in data:
        error = data["error"]
        if isinstance(error, dict):
            msg = error.get("message") or str(error)
        else:
            msg = str(error)
        raise ValueError(f"MCP server returned error for tools/list: {msg}")

    tools: list[dict[str, Any]] | None = None
    server_name: str | None = None

    if isinstance(data, dict):
        if isinstance(data.get("result"), dict):
            result = data["result"]
            if isinstance(result.get("tools"), list):
                tools = result["tools"]
            server_info = result.get("serverInfo")
            if isinstance(server_info, dict):
                raw_name = server_info.get("name")
                if isinstance(raw_name, str) and raw_name.strip():
                    server_name = raw_name.strip()
        elif isinstance(data.get("tools"), list):
            tools = data["tools"]

    if tools is None:
        msg = f"Invalid MCP tools/list response from {server_url}"
        raise ValueError(msg)

    if server_name is None:
        parsed = urlparse(server_url)
        server_name = parsed.hostname

    return tools, server_name
