"""MCP server: expose graph-tool-call as an MCP tool provider.

Usage::

    # CLI
    graph-tool-call serve --source https://petstore.swagger.io/v2/swagger.json

    # uvx (no install needed)
    uvx "graph-tool-call[mcp]" serve --source ./openapi.json

    # .mcp.json (Claude Code, Cursor, etc.)
    {
        "mcpServers": {
            "tool-search": {
                "command": "uvx",
                "args": ["graph-tool-call[mcp]", "serve",
                         "--source", "https://api.example.com/openapi.json"]
            }
        }
    }
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger("graph-tool-call.mcp")


def _check_mcp_installed() -> None:
    try:
        import mcp  # noqa: F401
    except ImportError:
        msg = 'MCP SDK not installed. Install with: pip install "graph-tool-call[mcp]"'
        raise ImportError(msg) from None


def create_mcp_server(
    sources: list[str] | None = None,
    *,
    graph_file: str | None = None,
    allow_private_hosts: bool = False,
) -> Any:
    """Create an MCP server backed by a ToolGraph.

    Parameters
    ----------
    sources:
        List of OpenAPI spec URLs or file paths to ingest at startup.
    graph_file:
        Pre-built graph JSON file to load instead of ingesting sources.
    allow_private_hosts:
        Allow localhost/private IP URLs for spec loading.
    """
    _check_mcp_installed()

    from mcp.server.fastmcp import FastMCP

    from graph_tool_call import ToolGraph
    from graph_tool_call.ontology.schema import NodeType

    mcp_app = FastMCP(
        "graph-tool-call",
        instructions=(
            "Tool search engine for LLM agents. "
            "Use search_tools() to find relevant tools by natural language query "
            "instead of browsing a large tool list. "
            "This dramatically reduces context size and improves tool selection accuracy."
        ),
    )

    # Build or load the ToolGraph
    tg: ToolGraph
    if graph_file:
        tg = ToolGraph.load(graph_file)
        logger.info("Loaded graph from %s: %d tools", graph_file, len(tg.tools))
    else:
        tg = ToolGraph()

    if sources:
        for source in sources:
            try:
                if source.startswith(("http://", "https://")):
                    loaded = ToolGraph.from_url(
                        source,
                        progress=lambda msg: logger.info(msg),
                        allow_private_hosts=allow_private_hosts,
                    )
                    # Merge into main graph
                    for tool in loaded.tools.values():
                        tg.add_tool(tool)
                else:
                    tg.ingest_openapi(
                        source,
                        allow_private_hosts=allow_private_hosts,
                    )
                logger.info("Ingested %s", source)
            except Exception as e:
                logger.warning("Failed to ingest %s: %s", source, e)

    # --- MCP Tools ---

    @mcp_app.tool()
    def search_tools(query: str, top_k: int = 5) -> str:
        """Search for relevant tools by natural language query.

        Returns the most relevant tools for the given query, ranked by
        graph-based hybrid retrieval (BM25 + graph traversal + embedding).

        Args:
            query: Natural language description of what you want to do.
                   Examples: "user authentication", "delete a file",
                   "manage shopping cart items"
            top_k: Maximum number of tools to return (default: 5)
        """
        if not tg.tools:
            return json.dumps({"error": "No tools loaded. Use load_source() first."})

        results = tg.retrieve(query, top_k=top_k)
        tools_out = []
        for tool in results:
            tool_dict: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
            }
            if tool.parameters:
                tool_dict["parameters"] = {
                    p.name: {
                        "type": p.type,
                        "description": p.description,
                        **({"required": True} if p.required else {}),
                    }
                    for p in tool.parameters
                }
            if tool.domain:
                tool_dict["category"] = tool.domain
            tools_out.append(tool_dict)

        return json.dumps(
            {
                "query": query,
                "count": len(tools_out),
                "total_tools": len(tg.tools),
                "tools": tools_out,
            },
            indent=2,
            ensure_ascii=False,
        )

    @mcp_app.tool()
    def get_tool_schema(name: str) -> str:
        """Get the full schema of a specific tool by name.

        Use this after search_tools() to get complete parameter details
        for a tool you want to call.

        Args:
            name: Exact tool name (as returned by search_tools)
        """
        tools = tg.tools
        if name not in tools:
            # Try case-insensitive match
            lower_map = {k.lower(): k for k in tools}
            if name.lower() in lower_map:
                name = lower_map[name.lower()]
            else:
                return json.dumps({"error": f"Tool '{name}' not found"})

        tool = tools[name]
        schema: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
        }
        if tool.parameters:
            schema["parameters"] = {
                p.name: {
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    **({"enum": p.enum} if p.enum else {}),
                    **({"default": p.default} if p.default is not None else {}),
                }
                for p in tool.parameters
            }
        if tool.method:
            schema["method"] = tool.method
        if tool.path:
            schema["path"] = tool.path
        if tool.domain:
            schema["category"] = tool.domain
        if tool.tags:
            schema["tags"] = tool.tags

        return json.dumps(schema, indent=2, ensure_ascii=False)

    @mcp_app.tool()
    def list_categories() -> str:
        """List all tool categories in the graph.

        Returns categories with their tool counts, useful for understanding
        the available tool landscape before searching.
        """
        categories: list[dict[str, Any]] = []
        for node_id in tg.graph.nodes():
            attrs = tg.graph.get_node_attrs(node_id)
            if attrs.get("node_type") == NodeType.CATEGORY:
                tool_count = len(
                    [
                        nb
                        for nb in tg.graph.get_neighbors(node_id, direction="in")
                        if tg.graph.get_node_attrs(nb).get("node_type") == NodeType.TOOL
                    ]
                )
                categories.append({"name": node_id, "tool_count": tool_count})

        categories.sort(key=lambda c: c["tool_count"], reverse=True)
        return json.dumps(
            {"count": len(categories), "categories": categories},
            indent=2,
            ensure_ascii=False,
        )

    @mcp_app.tool()
    def graph_info() -> str:
        """Show summary statistics about the loaded tool graph.

        Returns tool count, node count, edge count, and category breakdown.
        """
        tools = tg.tools
        info: dict[str, Any] = {
            "tool_count": len(tools),
            "node_count": tg.graph.node_count(),
            "edge_count": tg.graph.edge_count(),
        }

        # Node type breakdown
        type_counts: dict[str, int] = {}
        for node_id in tg.graph.nodes():
            attrs = tg.graph.get_node_attrs(node_id)
            nt = str(attrs.get("node_type", "unknown"))
            type_counts[nt] = type_counts.get(nt, 0) + 1
        info["node_types"] = type_counts

        # Relation type breakdown
        rel_counts: dict[str, int] = {}
        for _, _, attrs in tg.graph.edges():
            rel = str(attrs.get("relation", "unknown"))
            rel_counts[rel] = rel_counts.get(rel, 0) + 1
        if rel_counts:
            info["relation_types"] = rel_counts

        # Metadata
        if tg.metadata:
            info["source"] = tg.metadata.get("source_url", "")

        return json.dumps(info, indent=2, ensure_ascii=False)

    @mcp_app.tool()
    def execute_tool(
        tool_name: str,
        arguments: str,
        base_url: str = "",
        auth_token: str = "",
    ) -> str:
        """Execute an OpenAPI tool via HTTP.

        Sends the actual HTTP request based on the tool's method and path
        from the OpenAPI spec. Use after search_tools() + get_tool_schema()
        to call the API.

        Args:
            tool_name: Exact tool name (as returned by search_tools)
            arguments: JSON string of parameter values (e.g. '{"owner":"me","repo":"test"}')
            base_url: API base URL (e.g. https://api.github.com). Required if not inferrable.
            auth_token: Bearer token for authentication (optional)
        """
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid JSON arguments: {arguments}"})

        try:
            result = tg.execute(
                tool_name,
                args,
                base_url=base_url or None,
                auth_token=auth_token or None,
            )
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp_app.tool()
    def load_source(source: str) -> str:
        """Load additional tools from an OpenAPI spec URL or file path.

        Supports:
        - Direct spec URLs (JSON/YAML): https://api.example.com/openapi.json
        - Swagger UI URLs: https://api.example.com/swagger-ui/index.html
        - Local file paths: ./openapi.json, /path/to/spec.yaml

        Args:
            source: OpenAPI spec URL or local file path
        """
        try:
            before = len(tg.tools)
            if source.startswith(("http://", "https://")):
                loaded = ToolGraph.from_url(
                    source,
                    allow_private_hosts=allow_private_hosts,
                )
                for tool in loaded.tools.values():
                    tg.add_tool(tool)
            else:
                tg.ingest_openapi(source, allow_private_hosts=allow_private_hosts)
            after = len(tg.tools)
            return json.dumps(
                {
                    "status": "ok",
                    "source": source,
                    "tools_added": after - before,
                    "total_tools": after,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    return mcp_app


def run_server(
    sources: list[str] | None = None,
    *,
    graph_file: str | None = None,
    allow_private_hosts: bool = False,
    transport: str = "stdio",
) -> None:
    """Create and run the MCP server."""
    try:
        mcp_app = create_mcp_server(
            sources,
            graph_file=graph_file,
            allow_private_hosts=allow_private_hosts,
        )
    except ImportError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    mcp_app.run(transport=transport)
