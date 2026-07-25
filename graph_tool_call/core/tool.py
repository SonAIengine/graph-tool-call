"""Tool schema: unified internal representation for OpenAI / Anthropic / LangChain / MCP tools."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

# camelCase → snake_case mapping for MCP annotations
_MCP_ANNOTATION_MAP = {
    "title": "title",
    "readOnlyHint": "read_only_hint",
    "destructiveHint": "destructive_hint",
    "idempotentHint": "idempotent_hint",
    "openWorldHint": "open_world_hint",
}
_MCP_ANNOTATION_REVERSE = {v: k for k, v in _MCP_ANNOTATION_MAP.items()}


@dataclass
class MCPAnnotations:
    """MCP tool annotations (behavioral semantics).

    See: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
    """

    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    @classmethod
    def from_mcp_dict(cls, data: dict[str, Any]) -> MCPAnnotations:
        """Parse from MCP camelCase dict."""
        kwargs = {}
        for camel, snake in _MCP_ANNOTATION_MAP.items():
            value = data.get(camel)
            if camel == "title":
                if isinstance(value, str) and value.strip():
                    kwargs[snake] = value.strip()
            elif isinstance(value, bool):
                kwargs[snake] = value
        return cls(**kwargs)

    def to_mcp_dict(self) -> dict[str, Any]:
        """Serialize to MCP camelCase dict (omitting None values)."""
        result: dict[str, Any] = {}
        for snake, camel in _MCP_ANNOTATION_REVERSE.items():
            val = getattr(self, snake)
            if val is not None:
                result[camel] = val
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (omitting None values)."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def model_dump(self) -> dict[str, Any]:
        """Compatibility shim for code that used pydantic's model_dump()."""
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ToolParameter:
    """Single parameter of a tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
        }
        if self.enum is not None:
            d["enum"] = list(self.enum)
        else:
            d["enum"] = None
        return d

    def model_dump(self) -> dict[str, Any]:
        """Compatibility shim for code that used pydantic's model_dump()."""
        return self.to_dict()


@dataclass
class ToolSchema:
    """Internal unified tool representation."""

    name: str
    description: str = ""
    parameters: list[ToolParameter] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    domain: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: MCPAnnotations | None = None

    # keep the original callable if available (for LangChain tool execution)
    _callable: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Auto-convert dicts to proper dataclass instances during deserialization."""
        # parameters: list of dicts → list of ToolParameter
        if self.parameters and isinstance(self.parameters[0], dict):
            self.parameters = [ToolParameter(**p) for p in self.parameters]
        # annotations: dict → MCPAnnotations
        if isinstance(self.annotations, dict):
            self.annotations = MCPAnnotations(**self.annotations)

    def set_callable(self, fn: Any) -> None:
        self._callable = fn

    def get_callable(self) -> Any:
        return self._callable

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (recursive)."""
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "tags": list(self.tags),
            "domain": self.domain,
            "metadata": dict(self.metadata),
        }
        if self.annotations is not None:
            d["annotations"] = self.annotations.model_dump()
        else:
            d["annotations"] = None
        return d

    def model_dump(self) -> dict[str, Any]:
        """Compatibility shim for code that used pydantic's model_dump()."""
        return self.to_dict()


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

        {"name": ..., "title": ..., "description": ...,
         "inputSchema": {"type": "object", "properties": ...},
         "outputSchema": {"type": "object", "properties": ...},
         "annotations": {"readOnlyHint": true, ...},
         "execution": {"taskSupport": "optional"}}
    """
    params: list[ToolParameter] = []
    raw_schema = tool.get("inputSchema")
    input_schema = (
        copy.deepcopy(raw_schema)
        if isinstance(raw_schema, dict) and raw_schema.get("type", "object") == "object"
        else {"type": "object", "properties": {}}
    )
    properties = (
        input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
    )
    required_names = {
        str(name) for name in input_schema.get("required", []) if isinstance(name, str)
    }
    for pname, raw_parameter_schema in properties.items():
        pschema = raw_parameter_schema if isinstance(raw_parameter_schema, dict) else {}
        params.append(
            ToolParameter(
                name=str(pname),
                type=str(pschema.get("type") or "string"),
                description=str(pschema.get("description") or ""),
                required=str(pname) in required_names,
                enum=(
                    copy.deepcopy(pschema.get("enum"))
                    if isinstance(pschema.get("enum"), list)
                    else None
                ),
            )
        )

    annotations = None
    raw_annotations = tool.get("annotations")
    if isinstance(raw_annotations, dict):
        annotations = MCPAnnotations.from_mcp_dict(raw_annotations)

    raw_output_schema = tool.get("outputSchema")
    output_schema = (
        copy.deepcopy(raw_output_schema)
        if isinstance(raw_output_schema, dict)
        and raw_output_schema.get("type", "object") == "object"
        else None
    )
    from graph_tool_call.graphify.io_contract import build_io_contract

    produces, consumes = build_io_contract(
        request_body_schema=input_schema,
        response_schema=output_schema,
    )
    title = str(tool.get("title") or "").strip()
    annotation_title = annotations.title.strip() if annotations and annotations.title else ""
    execution = tool.get("execution") if isinstance(tool.get("execution"), dict) else {}
    task_support = str(execution.get("taskSupport") or "")
    safe_execution = (
        {"taskSupport": task_support}
        if task_support in {"forbidden", "optional", "required"}
        else {}
    )
    mcp_metadata: dict[str, Any] = {
        "display_title": title or annotation_title or str(tool.get("name") or ""),
        "annotations_trusted": False,
        "input_schema": copy.deepcopy(input_schema),
    }
    if title:
        mcp_metadata["title"] = title
    if output_schema is not None:
        mcp_metadata["output_schema"] = copy.deepcopy(output_schema)
    if safe_execution:
        mcp_metadata["execution"] = safe_execution

    metadata: dict[str, Any] = {
        "source": "mcp",
        "request_body_schema": copy.deepcopy(input_schema),
        "api_contract": {
            "produces": produces,
            "consumes": consumes,
            "links": [],
        },
        "mcp": mcp_metadata,
        "execution": {
            "transport": "mcp",
            "executable": False,
            **safe_execution,
        },
    }
    if output_schema is not None:
        metadata["response_schema"] = copy.deepcopy(output_schema)

    return ToolSchema(
        name=str(tool["name"]),
        description=str(tool.get("description") or ""),
        parameters=params,
        metadata=metadata,
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
    "insert": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "register": MCPAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "regist": MCPAnnotations(  # 일부 코드베이스 약어 (regUser, registOrder)
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    ),
    "reg": MCPAnnotations(  # camelCase 짧은 약어 (regGoodsApprove)
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
