"""Tool schema: unified internal representation for OpenAI / Anthropic / LangChain / MCP tools."""

from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# Post-ingest normalization
# ---------------------------------------------------------------------------

_VERB_TOKENS = frozenset(
    {
        "get",
        "set",
        "create",
        "update",
        "delete",
        "remove",
        "list",
        "fetch",
        "find",
        "search",
        "add",
        "put",
        "patch",
        "post",
        "read",
        "write",
        "show",
        "check",
        "verify",
        "validate",
        "process",
        "handle",
        "run",
        "execute",
        "send",
        "save",
        "load",
        "export",
        "import",
        "init",
        "start",
        "stop",
        "cancel",
        "close",
        "open",
        "enable",
        "disable",
    }
)

_ANNOTATION_BY_VERB: dict[str, MCPAnnotations] = {
    # read-only verbs
    "get": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "list": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "fetch": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "read": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "search": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "find": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "show": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "check": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "verify": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "validate": MCPAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    # create verbs
    "create": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "add": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "post": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "send": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    # update verbs
    "update": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "set": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "put": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "save": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
    ),
    "patch": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    # delete verbs
    "delete": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
    ),
    "remove": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
    ),
    "cancel": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
    ),
    "destroy": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
    ),
}


def _tokenize_name(name: str) -> list[str]:
    """Split a tool name into lowercase tokens (camelCase, snake_case, kebab-case)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return [t.lower() for t in spaced.split() if t]


def _singularize(word: str) -> str:
    """Naive English singularization for common plural suffixes."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _infer_tags(name: str) -> list[str]:
    """Infer resource-oriented tags from a tool name."""
    tokens = _tokenize_name(name)
    resource = [_singularize(t) for t in tokens if t not in _VERB_TOKENS]
    return resource if resource else [_singularize(t) for t in tokens[:1]]


def _infer_domain(tool: ToolSchema) -> str:
    """Infer domain from tags or fall back to 'general'."""
    if tool.tags:
        return tool.tags[0]
    return "general"


def _infer_annotations(name: str) -> MCPAnnotations | None:
    """Infer MCP annotations from the leading verb of a tool name."""
    tokens = _tokenize_name(name)
    if tokens and tokens[0] in _ANNOTATION_BY_VERB:
        return _ANNOTATION_BY_VERB[tokens[0]]
    return None


def normalize_tool(tool: ToolSchema) -> ToolSchema:
    """Ensure all ToolSchema fields are populated regardless of ingest source.

    Fills gaps only — existing values are never overwritten.
    This guarantees consistent field coverage for graph construction
    and retrieval scoring across all ingest sources (OpenAPI, MCP,
    Python functions, manual registration).
    """
    if not tool.tags:
        tool.tags = _infer_tags(tool.name)
    if tool.domain is None:
        tool.domain = _infer_domain(tool)
    if tool.annotations is None:
        tool.annotations = _infer_annotations(tool.name)
    return tool
