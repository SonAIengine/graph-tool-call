"""Conversion utilities between LangChain tools and internal ToolSchema."""

from __future__ import annotations

from typing import Any

from graph_tool_call.core.tool import ToolSchema


def tool_schema_to_openai_function(tool: ToolSchema) -> dict[str, Any]:
    """Convert internal ToolSchema to OpenAI function-calling format."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in tool.parameters:
        prop: dict[str, Any] = {"type": param.type, "description": param.description}
        if param.enum:
            prop["enum"] = param.enum
        properties[param.name] = prop
        if param.required:
            required.append(param.name)

    result: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
        },
    }
    if properties:
        result["function"]["parameters"] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["function"]["parameters"]["required"] = required

    return result


def langchain_tools_to_schemas(tools: list[Any]) -> list[ToolSchema]:
    """Convert a list of LangChain tools to internal ToolSchemas."""
    from graph_tool_call.core.tool import parse_langchain_tool

    return [parse_langchain_tool(t) for t in tools]
