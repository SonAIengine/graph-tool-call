"""Ingest MCP (Model Context Protocol) tool lists into ToolSchema instances."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from graph_tool_call.core.tool import ToolSchema, normalize_tool, parse_mcp_tool
from graph_tool_call.net import post_json


@dataclass(frozen=True)
class MCPToolCatalog:
    """Normalized metadata from a bare or JSON-RPC ``tools/list`` payload."""

    tools: list[dict[str, Any]]
    server_name: str | None = None
    server_version: str | None = None
    protocol_version: str | None = None
    next_cursor: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_tools: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tool_count": len(self.tools),
            "server_name": self.server_name,
            "server_version": self.server_version,
            "protocol_version": self.protocol_version,
            "next_cursor_present": bool(self.next_cursor),
            "capabilities": copy.deepcopy(self.capabilities),
        }
        if include_tools:
            result["tools"] = copy.deepcopy(self.tools)
        return result


def extract_mcp_tool_catalog(source: Any) -> MCPToolCatalog:
    """Normalize a bare list, catalog mapping, or JSON-RPC ``tools/list`` response.

    The helper keeps only protocol-defined catalog fields. Tool ``_meta`` and icon
    payloads remain in the returned raw rows for callers that explicitly need
    them, while :func:`parse_mcp_tool` deliberately excludes those untrusted
    fields from canonical metadata.
    """

    if isinstance(source, list):
        payload: dict[str, Any] = {"tools": source}
        envelope: dict[str, Any] = {}
    elif isinstance(source, dict):
        envelope = source
        result = source.get("result")
        payload = result if isinstance(result, dict) else source
    else:
        raise TypeError("MCP catalog must be a tool list or tools/list response mapping")

    rows = payload.get("tools")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError("MCP catalog must contain a list of tool mappings")

    raw_server_info = payload.get("serverInfo")
    if not isinstance(raw_server_info, dict):
        raw_server_info = envelope.get("serverInfo")
    server_info = raw_server_info if isinstance(raw_server_info, dict) else {}
    raw_capabilities = payload.get("capabilities")
    if not isinstance(raw_capabilities, dict):
        raw_capabilities = envelope.get("capabilities")
    capabilities: dict[str, Any] = {}
    if isinstance(raw_capabilities, dict):
        tools_capability = raw_capabilities.get("tools")
        if isinstance(tools_capability, dict) and isinstance(
            tools_capability.get("listChanged"), bool
        ):
            capabilities["tools"] = {
                "listChanged": tools_capability["listChanged"],
            }

    def _optional_text(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    return MCPToolCatalog(
        tools=copy.deepcopy(rows),
        server_name=_optional_text(server_info.get("name")),
        server_version=_optional_text(server_info.get("version")),
        protocol_version=_optional_text(
            payload.get("protocolVersion") or envelope.get("protocolVersion")
        ),
        next_cursor=_optional_text(payload.get("nextCursor")),
        capabilities=copy.deepcopy(capabilities),
    )


def ingest_mcp_tools(
    tools: list[dict[str, Any]],
    *,
    server_name: str | None = None,
) -> list[ToolSchema]:
    """Parse an already validated, fully paginated MCP tool list.

    Parameters
    ----------
    tools:
        Trusted list of MCP tool dicts with ``name``, ``description``,
        ``inputSchema``, and optional ``annotations``. Use ``ingest_source``
        for untrusted catalog diagnostics and shape limits.
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
            mcp_metadata = schema.metadata.get("mcp")
            if isinstance(mcp_metadata, dict):
                mcp_metadata.setdefault("server_name", server_name)
            if server_name not in schema.tags:
                schema.tags.append(server_name)
        normalize_tool(schema)
        result.append(schema)
    return result


def fetch_mcp_tools(
    server_url: str,
    *,
    allow_partial_catalog: bool = False,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one MCP ``tools/list`` response from an HTTP JSON-RPC endpoint.

    This convenience helper does not implement a stateful MCP transport
    session. A paginated response therefore fails closed unless the caller
    explicitly opts into a partial preview.
    """
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

    try:
        catalog = extract_mcp_tool_catalog(data)
    except TypeError:
        msg = f"Invalid MCP tools/list response from {server_url}"
        raise ValueError(msg) from None

    if catalog.next_cursor and not allow_partial_catalog:
        raise ValueError(
            "MCP tools/list response is paginated; use a session-aware MCP client "
            "to fetch every page or set allow_partial_catalog=True for preview only"
        )

    tools = catalog.tools
    server_name = catalog.server_name
    if server_name is None:
        parsed = urlparse(server_url)
        server_name = parsed.hostname

    return tools, server_name


__all__ = [
    "MCPToolCatalog",
    "extract_mcp_tool_catalog",
    "fetch_mcp_tools",
    "ingest_mcp_tools",
]
