"""MCP Proxy: aggregate multiple MCP servers and filter tools via ToolGraph.

Sits between an MCP client (Claude Code, Cursor, etc.) and real MCP servers.
Collects all backend tools, builds a ToolGraph, and exposes smart meta-tools
to keep the LLM context minimal.

Modes
-----
- **gateway** (default, ``tool_count > passthrough_threshold``):
  Exposes ``search_tools`` + ``get_tool_schema`` meta-tools.
  After search, matched tools are dynamically injected into ``tools/list``
  and a ``tools/list_changed`` notification is sent, enabling **1-hop direct
  calling** (no ``call_backend_tool`` wrapper needed).

  Fallback: ``call_backend_tool`` is kept for clients that don't support
  ``tools/list_changed``.

- **passthrough** (``tool_count <= passthrough_threshold``):
  All backend tools are exposed directly — no proxy overhead.

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
        "top_k": 10,
        "embedding": true,
        "passthrough_threshold": 30
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

# Default: if total tools <= this, expose all directly (no gateway overhead)
DEFAULT_PASSTHROUGH_THRESHOLD = 30

# Meta-tool names (reserved, not routed to backends)
_META_TOOLS = frozenset({"search_tools", "get_tool_schema", "call_backend_tool"})


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
        top_k: int = 10,
        embedding: bool = False,
        passthrough_threshold: int = DEFAULT_PASSTHROUGH_THRESHOLD,
    ):
        self._backends_config = backends
        self._connections: dict[str, BackendConnection] = {}
        self._tool_to_backend: dict[str, str] = {}
        self._all_tools: dict[str, Any] = {}  # name -> mcp.types.Tool
        self._tg: Any = None  # ToolGraph
        self._top_k = top_k
        self._embedding = embedding
        self._passthrough_threshold = passthrough_threshold
        self._gateway_mode: bool = False  # determined after connect
        self._exit_stack: AsyncExitStack | None = None
        # Dynamic tool injection: tools exposed after search
        self._exposed_tools: dict[str, Any] = {}  # name -> mcp.types.Tool

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
    def backend_count(self) -> int:
        return len(self._connections)

    @property
    def is_gateway_mode(self) -> bool:
        return self._gateway_mode

    async def connect_backends(self) -> None:
        """Connect to all backend MCP servers via stdio, collect tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

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
                logger.info("Connected to %s: %d tools", cfg.name, len(tools))
                conn = BackendConnection(config=cfg, session=session, tools=tools)
            except Exception as exc:
                logger.warning("Failed to connect to %s: %s", cfg.name, exc)
                continue
            self._connections[cfg.name] = conn
            for tool in conn.tools:
                name = tool.name
                if name in self._tool_to_backend:
                    original_backend = self._tool_to_backend[name]
                    logger.warning(
                        "Tool name collision: '%s' from '%s' and '%s'. "
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

        # Decide mode
        total = len(self._all_tools)
        self._gateway_mode = total > self._passthrough_threshold
        mode = "gateway" if self._gateway_mode else "passthrough"
        logger.info(
            "Proxy ready: %d backends, %d tools, mode=%s",
            len(self._connections),
            total,
            mode,
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

        # Enable embedding for cross-language search
        if self._embedding and self._tg.tools:
            try:
                self._tg.enable_embedding()
                logger.info("Embedding enabled (%d tools indexed)", len(self._tg.tools))
            except Exception as exc:
                logger.warning("Embedding unavailable, BM25-only: %s", exc)

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Search tools via ToolGraph. Returns lightweight results (no inputSchema).

        After search, matched tools are stored in ``_exposed_tools`` for
        dynamic injection into ``tools/list``.
        """
        k = top_k or self._top_k
        results = self._tg.retrieve_with_scores(query, top_k=k)

        # Zero-result fallback
        if not results:
            return [
                {
                    "error": "No matching tools found.",
                    "suggestion": "Try a different query or use English keywords.",
                    "total_tools": len(self._all_tools),
                }
            ]

        # Update exposed tools for dynamic injection
        self._exposed_tools.clear()

        out: list[dict[str, Any]] = []
        for r in results:
            proxy_name = r.tool.name
            mcp_tool = self._all_tools.get(proxy_name)
            if not mcp_tool:
                for pn in self._all_tools:
                    if pn.endswith(f"__{r.tool.name}"):
                        proxy_name = pn
                        mcp_tool = self._all_tools[pn]
                        break

            entry: dict[str, Any] = {
                "name": proxy_name,
                "description": r.tool.description,
                "score": round(r.score, 4),
                "confidence": r.confidence,
            }
            if r.tool.domain:
                entry["category"] = r.tool.domain
            out.append(entry)

            # Register for dynamic injection
            if mcp_tool:
                self._exposed_tools[proxy_name] = mcp_tool

        return out

    def get_tool_schema(self, name: str) -> dict[str, Any] | None:
        """Get full schema for a specific tool."""
        mcp_tool = self._all_tools.get(name)
        if not mcp_tool:
            return None

        schema: dict[str, Any] = {
            "name": name,
            "description": mcp_tool.description or "",
        }
        if mcp_tool.inputSchema:
            schema["inputSchema"] = mcp_tool.inputSchema
        return schema

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Route a tool call to the correct backend."""
        backend_name = self._tool_to_backend.get(name)
        if not backend_name:
            from mcp import types

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"Tool '{name}' not found. Use search_tools to find the correct name.",
                    )
                ],
                isError=True,
            )

        conn = self._connections[backend_name]
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
    - Native: ``{"backends": {"name": {"command": ..., "args": [...]}}}``
    - .mcp.json: ``{"mcpServers": {"name": {"command": ..., "args": [...]}}}``
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

    In **gateway mode** (many tools), exposes ``search_tools``,
    ``get_tool_schema``, and ``call_backend_tool`` meta-tools.
    After search, matched backend tools are dynamically injected
    into ``tools/list`` for 1-hop direct calling.

    In **passthrough mode** (few tools), exposes all backend tools directly.
    """
    _check_mcp_installed()

    from mcp.server.lowlevel import Server

    server = Server("graph-tool-call-proxy")

    if proxy.is_gateway_mode:
        return _create_gateway_server(server, proxy)
    return _create_passthrough_server(server, proxy)


def _create_gateway_server(server: Any, proxy: MCPProxy) -> Any:
    """Gateway mode: search + get_schema + dynamic tool injection.

    After ``search_tools`` is called, matched backend tools are added to
    ``proxy._exposed_tools``.  On the next ``tools/list`` request (triggered
    by the SDK's automatic cache-miss refresh), those tools appear as
    first-class callable tools — enabling **1-hop direct calling**.
    """
    import mcp.types as types

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        meta_tools = [
            types.Tool(
                name="search_tools",
                description=(
                    f"Search across {len(proxy._all_tools)} tools from "
                    f"{proxy.backend_count} MCP servers. Returns matching "
                    "tools ranked by relevance. After search, matched tools "
                    "become directly callable by name."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Describe what you want to do. Use English for best results."
                            ),
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max results (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="get_tool_schema",
                description=(
                    "Get the full inputSchema of a specific tool. "
                    "Use after search_tools to see exact parameters "
                    "before calling the tool."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Exact tool name from search_tools results",
                        },
                    },
                    "required": ["tool_name"],
                },
            ),
            types.Tool(
                name="call_backend_tool",
                description=(
                    "Call a backend tool by name (fallback). "
                    "Prefer calling tools directly by name after search. "
                    "Use this only if direct calling is not available."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Exact tool name from search_tools results",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments matching the tool's inputSchema",
                        },
                    },
                    "required": ["tool_name"],
                },
            ),
        ]

        # Dynamically injected backend tools from last search
        for name, mcp_tool in proxy._exposed_tools.items():
            meta_tools.append(
                types.Tool(
                    name=name,
                    description=mcp_tool.description or "",
                    inputSchema=mcp_tool.inputSchema if mcp_tool.inputSchema else {},
                )
            )

        return meta_tools

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        # --- Meta-tool: search_tools ---
        if name == "search_tools":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", proxy._top_k)
            results = proxy.search(query, top_k=top_k)

            output = json.dumps(
                {
                    "query": query,
                    "matched": len(results),
                    "total_tools": len(proxy._all_tools),
                    "tools": results,
                    "hint": (
                        "Matched tools are now directly callable by name. "
                        "Use get_tool_schema to see full parameters if needed."
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
            return [types.TextContent(type="text", text=output)]

        # --- Meta-tool: get_tool_schema ---
        if name == "get_tool_schema":
            tool_name = arguments.get("tool_name", "")
            schema = proxy.get_tool_schema(tool_name)
            if schema is None:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps({"error": f"Tool '{tool_name}' not found"}),
                    )
                ]
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(schema, indent=2, ensure_ascii=False),
                )
            ]

        # --- Meta-tool: call_backend_tool (fallback) ---
        if name == "call_backend_tool":
            tool_name = arguments.get("tool_name", "")
            tool_args = arguments.get("arguments", {})
            result = await proxy.call_tool(tool_name, tool_args)
            return result.content

        # --- Direct backend tool routing ---
        if name in proxy._tool_to_backend:
            result = await proxy.call_tool(name, arguments)
            return result.content

        return [
            types.TextContent(
                type="text",
                text=f"Tool '{name}' not found. Use search_tools first.",
            )
        ]

    return server


def _create_passthrough_server(server: Any, proxy: MCPProxy) -> Any:
    """Passthrough mode: expose all backend tools directly."""
    import mcp.types as types

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        result: list[types.Tool] = []
        for name, tool in proxy._all_tools.items():
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
        result = await proxy.call_tool(name, arguments)
        return result.content

    return server


async def _run_proxy_async(
    backends: list[BackendConfig],
    *,
    top_k: int = 10,
    embedding: bool = False,
    passthrough_threshold: int = DEFAULT_PASSTHROUGH_THRESHOLD,
) -> None:
    """Run the proxy server (async entry point)."""
    import mcp.server.stdio

    proxy = MCPProxy(
        backends,
        top_k=top_k,
        embedding=embedding,
        passthrough_threshold=passthrough_threshold,
    )

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
    top_k: int = 10,
    embedding: bool = False,
    passthrough_threshold: int = DEFAULT_PASSTHROUGH_THRESHOLD,
) -> None:
    """Run the MCP proxy (blocking entry point)."""
    try:
        _check_mcp_installed()
    except ImportError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    import asyncio

    asyncio.run(
        _run_proxy_async(
            backends,
            top_k=top_k,
            embedding=embedding,
            passthrough_threshold=passthrough_threshold,
        )
    )
