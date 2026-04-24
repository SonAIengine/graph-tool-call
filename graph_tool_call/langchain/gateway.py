"""LangChain gateway tools — search & call pattern.

Converts a large tool list into 2 meta-tools that an LLM agent can use:

- ``search_tools``: BM25 + Graph search over tool names/descriptions
- ``call_tool``: Execute a tool by name with arguments

Usage::

    from graph_tool_call.langchain import create_gateway_tools

    # Original tools (50~500+)
    all_tools = [tool1, tool2, ..., tool200]

    # Convert to 2 gateway meta-tools
    gateway_tools = create_gateway_tools(all_tools, top_k=10)

    # Use with any LangChain agent
    agent = create_react_agent(model=llm, tools=gateway_tools)
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("graph-tool-call.langchain.gateway")


def _extract_parameters_info(tool: Any) -> list[dict[str, Any]] | None:
    """Extract parameter info from a LangChain tool for search results."""
    # LangChain BaseTool with args_schema (Pydantic model)
    if hasattr(tool, "args_schema") and tool.args_schema is not None:
        try:
            schema = tool.args_schema.model_json_schema()
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            params = []
            for name, info in props.items():
                param = {
                    "name": name,
                    "type": info.get("type", "string"),
                    "required": name in required,
                }
                if "description" in info:
                    param["description"] = info["description"]
                params.append(param)
            return params if params else None
        except Exception:
            pass

    # LangChain tool with .args property (dict schema)
    if hasattr(tool, "args") and isinstance(tool.args, dict):
        try:
            params = []
            for name, info in tool.args.items():
                param = {"name": name, "type": info.get("type", "string")}
                if "description" in info:
                    param["description"] = info["description"]
                params.append(param)
            return params if params else None
        except Exception:
            pass

    return None


def _summarize_response_schema(schema: dict[str, Any]) -> str | None:
    """Produce a one-line summary of an OpenAPI response schema for the LLM.

    Lists top-level field names + types so the model can plan parameter
    extraction for the next call.
    """
    if not isinstance(schema, dict):
        return None

    # Unwrap arrays
    container = schema
    is_array = False
    if container.get("type") == "array" and isinstance(container.get("items"), dict):
        container = container["items"]
        is_array = True

    props = container.get("properties")
    if not isinstance(props, dict) or not props:
        # Fall back to a bare type description
        t = container.get("type")
        return f"array of {t}" if is_array and t else t

    fields = []
    for name, info in list(props.items())[:12]:
        if not isinstance(info, dict):
            fields.append(name)
            continue
        t = info.get("type") or info.get("$ref", "object").rsplit("/", 1)[-1]
        fields.append(f"{name}:{t}")
    summary = "{" + ", ".join(fields) + "}"
    return f"array of {summary}" if is_array else summary


def _enrich_from_graph(
    name: str, graph: Any | None
) -> dict[str, Any]:
    """Pull source_label, method/path, response summary, and outgoing edges
    from the underlying ToolGraph for *name*. Returns an empty dict if the
    graph or tool is not available — callers should treat all keys as optional.
    """
    if graph is None:
        return {}

    enrichment: dict[str, Any] = {}

    tool_schema = None
    try:
        tool_schema = graph.tools.get(name)
    except Exception:
        return enrichment

    if tool_schema is not None and getattr(tool_schema, "metadata", None):
        meta = tool_schema.metadata
        if meta.get("source_label"):
            enrichment["source"] = meta["source_label"]
        if meta.get("method") and meta.get("path"):
            enrichment["http"] = f"{meta['method'].upper()} {meta['path']}"
        rs = meta.get("response_schema")
        if isinstance(rs, dict):
            summary = _summarize_response_schema(rs)
            if summary:
                enrichment["returns"] = summary

    # Outgoing edges → chain hints
    try:
        engine = graph.graph
        edges = engine.get_edges_from(name, direction="out")
        chains: list[str] = []
        for _src, target, attrs in edges:
            relation = attrs.get("relation")
            relation_name = (
                relation.value if hasattr(relation, "value") else str(relation)
            )
            # Skip purely structural BELONGS_TO edges
            if relation_name in ("belongs_to", "BELONGS_TO"):
                continue
            chains.append(f"{relation_name}→{target}")
            if len(chains) >= 5:
                break
        if chains:
            enrichment["next_candidates"] = chains
    except Exception:
        pass

    return enrichment


def create_gateway_tools(
    tools: list[Any],
    *,
    top_k: int = 10,
    graph: Any | None = None,
    compress_results: bool = False,
    compress_max_chars: int = 4000,
) -> list[Any]:
    """Create 2 gateway meta-tools from a list of LangChain tools.

    Parameters
    ----------
    tools:
        Full list of tools (LangChain ``BaseTool``, callables, etc.).
    top_k:
        Default number of results for ``search_tools`` (default: 10).
    graph:
        Optional pre-built ``ToolGraph``. If *None*, one is built from *tools*.
    compress_results:
        When True, compress large ``call_tool`` responses to save context tokens.
    compress_max_chars:
        Maximum characters for compressed output (default: 4000).

    Returns
    -------
    list
        Two LangChain tools: ``[search_tools, call_tool]``.
    """
    from langchain_core.tools import tool as langchain_tool

    from graph_tool_call.langchain.toolkit import GraphToolkit, _extract_name

    # Build toolkit (reuses ToolGraph internally)
    toolkit = GraphToolkit(tools=tools, top_k=top_k, graph=graph)

    # Build tool map for call_tool dispatch
    tool_map: dict[str, Any] = {}
    for t in tools:
        name = _extract_name(t)
        if name:
            tool_map[name] = t

    total = len(tool_map)
    call_history: list[str] = []

    underlying_graph = getattr(toolkit, "graph", None)

    @langchain_tool
    def search_tools(query: str, top_k: int | None = None) -> str:
        """Search available tools by natural language query.

        Use this FIRST to find which tools are available for the task.
        Returns tool names, descriptions, parameters, response shape, and
        ``next_candidates`` (related tools you may want to call afterwards).

        Args:
            query: Natural language search query (e.g. "cancel order", "send email")
            top_k: Max number of results (optional)
        """
        k = top_k if top_k is not None else toolkit._top_k
        results = toolkit.get_tools(query, top_k=k)

        matched = []
        for t in results:
            name = _extract_name(t)
            desc = ""
            if hasattr(t, "description"):
                desc = t.description or ""
            elif isinstance(t, dict):
                desc = t.get("description", "")
            entry: dict[str, Any] = {
                "name": name,
                "description": desc[:300],
            }
            params = _extract_parameters_info(t)
            if params:
                entry["parameters"] = params
            entry.update(_enrich_from_graph(name, underlying_graph))
            matched.append(entry)

        output = {
            "query": query,
            "matched": len(matched),
            "total_tools": total,
            "tools": matched,
            "hint": (
                "Use call_tool to execute a tool. Pass tool_name and arguments "
                "as a dict matching the parameters above. The 'returns' field "
                "shows the response shape — extract values from there to build "
                "arguments for the next call (see 'next_candidates')."
            ),
        }

        logger.debug("search_tools(%r) → %d results", query, len(matched))
        return json.dumps(output, ensure_ascii=False, indent=2)

    @langchain_tool
    def call_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        """Execute a tool by name with arguments.

        Use after search_tools to call a specific tool.

        Args:
            tool_name: Exact tool name from search_tools results
            arguments: Tool arguments as a dict (e.g. {"order_id": 123, "city": "Seoul"})
        """
        target = tool_map.get(tool_name)
        if target is None:
            return json.dumps(
                {
                    "error": f"Tool '{tool_name}' not found.",
                    "hint": "Use search_tools to find the correct tool name.",
                }
            )

        # Normalize arguments
        args: dict[str, Any] = {}
        if arguments is not None:
            if isinstance(arguments, dict):
                args = arguments
            elif isinstance(arguments, str):
                try:
                    args = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}

        # Track call history for retrieval boost
        if tool_name not in call_history:
            call_history.append(tool_name)

        # Execute
        try:
            if hasattr(target, "invoke"):
                result = target.invoke(args)
            elif callable(target):
                result = target(**args)
            else:
                return json.dumps({"error": f"Tool '{tool_name}' is not callable."})

            if isinstance(result, str):
                result_str = result
            else:
                result_str = json.dumps(result, ensure_ascii=False, default=str)

            if compress_results and len(result_str) > compress_max_chars:
                from graph_tool_call.compressor import CompressConfig, compress_tool_result

                cfg = CompressConfig(max_chars=compress_max_chars)
                return compress_tool_result(result_str, config=cfg)
            return result_str
        except Exception as e:
            logger.warning("call_tool(%s) failed: %s", tool_name, e)
            return json.dumps(
                {
                    "error": str(e),
                    "tool_name": tool_name,
                }
            )

    return [search_tools, call_tool]
