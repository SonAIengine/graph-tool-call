"""Tool schema: unified internal representation for OpenAI / Anthropic / LangChain / MCP tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# camelCase → snake_case mapping for MCP annotations
_MCP_ANNOTATION_MAP = {
    "readOnlyHint": "read_only_hint",
    "destructiveHint": "destructive_hint",
    "idempotentHint": "idempotent_hint",
    "openWorldHint": "open_world_hint",
}
_MCP_ANNOTATION_REVERSE = {v: k for k, v in _MCP_ANNOTATION_MAP.items()}


class MCPAnnotations(BaseModel):
    """MCP tool annotations (behavioral semantics).

    See: https://spec.modelcontextprotocol.io/2025-03-26/server/tools/
    """

    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    @classmethod
    def from_mcp_dict(cls, data: dict[str, Any]) -> MCPAnnotations:
        """Parse from MCP camelCase dict."""
        kwargs = {}
        for camel, snake in _MCP_ANNOTATION_MAP.items():
            if camel in data:
                kwargs[snake] = data[camel]
        return cls(**kwargs)

    def to_mcp_dict(self) -> dict[str, Any]:
        """Serialize to MCP camelCase dict (omitting None values)."""
        result: dict[str, Any] = {}
        for snake, camel in _MCP_ANNOTATION_REVERSE.items():
            val = getattr(self, snake)
            if val is not None:
                result[camel] = val
        return result


class ToolParameter(BaseModel):
    """Single parameter of a tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: list[str] | None = None


class ToolSchema(BaseModel):
    """Internal unified tool representation."""

    name: str
    description: str = ""
    parameters: list[ToolParameter] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    domain: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    annotations: MCPAnnotations | None = None

    # keep the original callable if available (for LangChain tool execution)
    _callable: Any = None

    def set_callable(self, fn: Any) -> None:
        object.__setattr__(self, "_callable", fn)

    def get_callable(self) -> Any:
        return object.__getattribute__(self, "_callable")


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------


def parse_openai_tool(tool: dict[str, Any]) -> ToolSchema:
    """Parse OpenAI function-calling format.

    Expected shape:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    or legacy:
        {"name": ..., "description": ..., "parameters": ...}
    """
    if "function" in tool:
        func = tool["function"]
    else:
        func = tool

    params: list[ToolParameter] = []
    raw_params = func.get("parameters", {})
    required_names = set(raw_params.get("required", []))
    for pname, pschema in raw_params.get("properties", {}).items():
        params.append(
            ToolParameter(
                name=pname,
                type=pschema.get("type", "string"),
                description=pschema.get("description", ""),
                required=pname in required_names,
                enum=pschema.get("enum"),
            )
        )

    return ToolSchema(
        name=func["name"],
        description=func.get("description", ""),
        parameters=params,
    )


def parse_anthropic_tool(tool: dict[str, Any]) -> ToolSchema:
    """Parse Anthropic tool format.

    Expected shape:
        {"name": ..., "description": ..., "input_schema": {"type": "object", "properties": ...}}
    """
    params: list[ToolParameter] = []
    raw_schema = tool.get("input_schema", {})
    required_names = set(raw_schema.get("required", []))
    for pname, pschema in raw_schema.get("properties", {}).items():
        params.append(
            ToolParameter(
                name=pname,
                type=pschema.get("type", "string"),
                description=pschema.get("description", ""),
                required=pname in required_names,
                enum=pschema.get("enum"),
            )
        )

    return ToolSchema(
        name=tool["name"],
        description=tool.get("description", ""),
        parameters=params,
    )


def parse_langchain_tool(tool: Any) -> ToolSchema:
    """Parse a LangChain BaseTool instance into internal ToolSchema.

    Works with any object that has `.name`, `.description`, and optionally `.args_schema`.
    """
    params: list[ToolParameter] = []
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        schema = (
            args_schema.model_json_schema() if hasattr(args_schema, "model_json_schema") else {}
        )
        required_names = set(schema.get("required", []))
        for pname, pschema in schema.get("properties", {}).items():
            params.append(
                ToolParameter(
                    name=pname,
                    type=pschema.get("type", "string"),
                    description=pschema.get("description", ""),
                    required=pname in required_names,
                    enum=pschema.get("enum"),
                )
            )

    ts = ToolSchema(
        name=tool.name,
        description=getattr(tool, "description", "") or "",
        parameters=params,
    )
    ts.set_callable(tool)
    return ts


def parse_mcp_tool(tool: dict[str, Any]) -> ToolSchema:
    """Parse MCP tool format.

    Expected shape::

        {"name": ..., "description": ..., "inputSchema": {"type": "object", "properties": ...},
         "annotations": {"readOnlyHint": true, ...}}
    """
    params: list[ToolParameter] = []
    raw_schema = tool.get("inputSchema", {})
    required_names = set(raw_schema.get("required", []))
    for pname, pschema in raw_schema.get("properties", {}).items():
        params.append(
            ToolParameter(
                name=pname,
                type=pschema.get("type", "string"),
                description=pschema.get("description", ""),
                required=pname in required_names,
                enum=pschema.get("enum"),
            )
        )

    annotations = None
    raw_annotations = tool.get("annotations")
    if isinstance(raw_annotations, dict):
        annotations = MCPAnnotations.from_mcp_dict(raw_annotations)

    return ToolSchema(
        name=tool["name"],
        description=tool.get("description", ""),
        parameters=params,
        annotations=annotations,
    )


def parse_tool(tool: Any) -> ToolSchema:
    """Auto-detect format and parse into ToolSchema."""
    # Already a ToolSchema
    if isinstance(tool, ToolSchema):
        return tool

    # Dict-based formats
    if isinstance(tool, dict):
        if "inputSchema" in tool:
            return parse_mcp_tool(tool)
        if "input_schema" in tool:
            return parse_anthropic_tool(tool)
        return parse_openai_tool(tool)

    # Object with .name attribute → treat as LangChain-style tool
    if hasattr(tool, "name"):
        return parse_langchain_tool(tool)

    raise TypeError(f"Unsupported tool format: {type(tool)}")
