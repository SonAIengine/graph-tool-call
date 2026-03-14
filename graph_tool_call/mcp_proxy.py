"""MCP Proxy: aggregate multiple MCP servers and filter tools via ToolGraph.

Sits between an MCP client (Claude Code, Cursor, etc.) and real MCP servers.
Collects all backend tools, builds a ToolGraph, and dynamically filters
which tools are exposed to the client based on search queries.

Usage::

    # CLI
    graph-tool-call proxy --config backends.json

    # .mcp.json (Claude Code)
    {
        "mcpServers": {
            "smart-tools": {
                "command": "uvx",
                "args": ["graph-tool-call[mcp]", "proxy",
                         "--config", "/path/to/backends.json"]
            }
        }
    }

Config format (backends.json)::

    {
        "backends": {
            "playwright": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-playwright"]
            },
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-filesystem", "/home"]
            }
        },
        "top_k": 20
    }

Or use .mcp.json format directly (``mcpServers`` key).
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("graph-tool-call.mcp-proxy")


def _check_mcp_installed() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        msg = 'MCP SDK not installed. Install with: pip install "graph-tool-call[mcp]"'
        raise ImportError(msg) from None


@dataclass
class BackendConfig:
    """Configuration for one backend MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None


@dataclass
class BackendConnection:
    """Live connection to a backend MCP server."""

    config: BackendConfig
    session: Any  # mcp.ClientSession
    tools: list[Any] = field(default_factory=list)  # list[mcp.types.Tool]


class MCPProxy:
    """MCP proxy that aggregates backend servers and filters tools via ToolGraph."""

    def __init__(
        self,
        backends: list[BackendConfig],
        *,
        top_k: int = 20,
    ):
        self._backends_config = backends
        self._connections: dict[str, BackendConnection] = {}
        self._tool_to_backend: dict[str, str] = {}
        self._all_tools: dict[str, Any] = {}  # name -> mcp.types.Tool
        self._tg: Any = None  # ToolGraph
        self._top_k = top_k
        self._active_filter: set[str] | None = None
        self._exit_stack: AsyncExitStack | None = None

    @property
    def tool_graph(self) -> Any:
        return self._tg

    @property
    def all_tools(self) -> dict[str, Any]:
        return dict(self._all_tools)

    @property
    def tool_to_backend(self) -> dict[str, str]:
        return dict(self._tool_to_backend)

    @property
    def active_filter(self) -> set[str] | None:
        return self._active_filter

    @property
    def backend_count(self) -> int:
        return len(self._connections)

    async def connect_backends(self) -> None:
        """Connect to all backend MCP servers via stdio, collect tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        # Connect sequentially (stdio_client context managers must stay in same task)
        for cfg in self._backends_config:
            try:
                params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                )
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()
                result = await session.list_tools()
                tools = result.tools
                logger.info(
                    "Connected to %s: %d tools",
                    cfg.name,
                    len(tools),
                )
                conn = BackendConnection(config=cfg, session=session, tools=tools)
            except Exception as exc:
                logger.warning("Failed to connect to %s: %s", cfg.name, exc)
                continue
            self._connections[cfg.name] = conn
            for tool in conn.tools:
                name = tool.name
                if name in self._tool_to_backend:
                    # Name collision — prefix with backend name
                    original_backend = self._tool_to_backend[name]
                    logger.warning(
                        "Tool name collision: '%s' from both '%s' and '%s'. "
                        "Prefixing with backend name.",
                        name,
                        original_backend,
                        cfg.name,
                    )
                    prefixed = f"{cfg.name}__{name}"
                    self._tool_to_backend[prefixed] = cfg.name
                    self._all_tools[prefixed] = tool
                else:
                    self._tool_to_backend[name] = cfg.name
                    self._all_tools[name] = tool

        self._build_tool_graph()
        total = len(self._all_tools)
        logger.info(
            "Proxy ready: %d backends, %d total tools",
            len(self._connections),
            total,
        )

    def _build_tool_graph(self) -> None:
        """Build ToolGraph from all collected backend tools."""
        from graph_tool_call import ToolGraph

        self._tg = ToolGraph()
        for backend_name, conn in self._connections.items():
            tool_dicts = []
            for tool in conn.tools:
                d: dict[str, Any] = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if tool.inputSchema else {},
                }
                if hasattr(tool, "annotations") and tool.annotations:
                    try:
                        d["annotations"] = tool.annotations.model_dump(exclude_none=True)
                    except AttributeError:
                        pass
                tool_dicts.append(d)
            if tool_dicts:
                self._tg.ingest_mcp_tools(tool_dicts, server_name=backend_name)

    def get_filtered_tool_names(self) -> list[str]:
        """Return currently active tool name list."""
        if self._active_filter is not None:
            return [n for n in self._all_tools if n in self._active_filter]
        return list(self._all_tools.keys())

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Search tools via ToolGraph and update active filter."""
        k = top_k or self._top_k
        results = self._tg.retrieve(query, top_k=k)

        # Map ToolSchema names back to proxy tool names (handle prefixed names)
        matched_names: set[str] = set()
        for r in results:
            if r.name in self._all_tools:
                matched_names.add(r.name)
            else:
                # Check prefixed variants
                for proxy_name in self._all_tools:
                    if proxy_name.endswith(f"__{r.name}"):
                        matched_names.add(proxy_name)

        self._active_filter = matched_names

        return [
            {
                "name": r.name,
                "description": r.description,
                **({"category": r.domain} if r.domain else {}),
            }
            for r in results
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Route a tool call to the correct backend."""
        backend_name = self._tool_to_backend.get(name)
        if not backend_name:
            from mcp import types

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Tool '{name}' not found in any backend.",
                    )
                ],
                isError=True,
            )

        conn = self._connections[backend_name]
        # Resolve actual tool name (strip prefix if present)
        actual_name = name
        if "__" in name:
            actual_name = name.split("__", 1)[1]

        return await conn.session.call_tool(actual_name, arguments)

    async def shutdown(self) -> None:
        """Disconnect all backends."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._connections.clear()


def load_proxy_config(path: str) -> tuple[list[BackendConfig], dict[str, Any]]:
    """Load proxy configuration from a JSON file.

    Supports two formats:
    - Native proxy config: ``{"backends": {"name": {"command": ..., "args": [...]}}}``
    - .mcp.json format: ``{"mcpServers": {"name": {"command": ..., "args": [...]}}}``
    """
    with open(path) as f:
        data = json.load(f)

    if "mcpServers" in data:
        backends = []
        for name, server_def in data["mcpServers"].items():
            backends.append(
                BackendConfig(
                    name=name,
                    command=server_def["command"],
                    args=server_def.get("args", []),
                    env=server_def.get("env"),
                )
            )
        return backends, {}

    if "backends" in data:
        backends = []
        for name, server_def in data["backends"].items():
            backends.append(
                BackendConfig(
                    name=name,
                    command=server_def["command"],
                    args=server_def.get("args", []),
                    env=server_def.get("env"),
                )
            )
        options = {k: v for k, v in data.items() if k != "backends"}
        return backends, options

    msg = "Config must have 'backends' or 'mcpServers' key"
    raise ValueError(msg)


def create_proxy_server(
    proxy: MCPProxy,
) -> Any:
    """Create a low-level MCP Server wired to the proxy.

    Returns the ``mcp.server.lowlevel.Server`` instance.
    """
    _check_mcp_installed()

    import mcp.types as types
    from mcp.server.lowlevel import Server

    server = Server("graph-tool-call-proxy")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        # Meta-tool: search_tools
        search_tool = types.Tool(
            name="search_tools",
            description=(
                "Search for relevant tools by natural language query. "
                "Call this first to find the right tool instead of browsing "
                "the full list. After calling this, only matching tools will "
                "appear in subsequent tool listings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What you want to do",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Max results (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        )

        # Meta-tool: reset_filter
        reset_tool = types.Tool(
            name="reset_tool_filter",
            description=(
                "Reset tool filter to show all available tools. "
                "Use this after search_tools() if you need to browse "
                "the full tool list again."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        )

        result = [search_tool, reset_tool]

        # Add filtered or all backend tools
        active_names = proxy.get_filtered_tool_names()
        for name in active_names:
            tool = proxy._all_tools[name]
            # Re-create Tool with potentially prefixed name
            result.append(
                types.Tool(
                    name=name,
                    description=tool.description or "",
                    inputSchema=tool.inputSchema if tool.inputSchema else {},
                )
            )

        return result

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        # Meta-tool: search_tools
        if name == "search_tools":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", proxy._top_k)
            results = proxy.search(query, top_k=top_k)

            # Send list_changed notification so client refreshes tools
            try:
                await server.request_context.session.send_tool_list_changed()
            except Exception:
                pass  # Client may not support notifications

            output = json.dumps(
                {
                    "query": query,
                    "matched": len(results),
                    "total_tools": len(proxy._all_tools),
                    "tools": results,
                    "hint": (
                        "Tool list has been filtered. "
                        "The matched tools are now directly available to call."
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
            return [types.TextContent(type="text", text=output)]

        # Meta-tool: reset_tool_filter
        if name == "reset_tool_filter":
            proxy._active_filter = None
            try:
                await server.request_context.session.send_tool_list_changed()
            except Exception:
                pass
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "ok",
                            "total_tools": len(proxy._all_tools),
                            "message": "Filter reset. All tools are now visible.",
                        }
                    ),
                )
            ]

        # Route to backend
        result = await proxy.call_tool(name, arguments)
        return result.content

    return server


async def _run_proxy_async(
    backends: list[BackendConfig],
    *,
    top_k: int = 20,
) -> None:
    """Run the proxy server (async entry point)."""
    import mcp.server.stdio

    proxy = MCPProxy(backends, top_k=top_k)

    try:
        await proxy.connect_backends()
        server = create_proxy_server(proxy)

        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await proxy.shutdown()


def run_proxy(
    backends: list[BackendConfig],
    *,
    top_k: int = 20,
) -> None:
    """Run the MCP proxy (blocking entry point)."""
    try:
        _check_mcp_installed()
    except ImportError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    import asyncio

    asyncio.run(_run_proxy_async(backends, top_k=top_k))
