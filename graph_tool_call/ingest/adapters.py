"""Extensible adapters for turning heterogeneous API catalogs into ToolSchema."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from graph_tool_call.core.tool import ToolSchema, normalize_tool, parse_tool


@dataclass(frozen=True)
class IngestCapabilities:
    """Open-ended capability declaration for an ingest adapter."""

    source_type: str
    features: frozenset[str] = frozenset()
    transports: frozenset[str] = frozenset()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "features": sorted(self.features),
            "transports": sorted(self.transports),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class IngestIssue:
    """Stable, product-neutral diagnostic emitted during ingest."""

    severity: str
    code: str
    message: str
    tool: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": dict(self.evidence),
        }
        if self.tool is not None:
            result["tool"] = self.tool
        return result


@dataclass
class IngestResult:
    """Canonical output shared by built-in and third-party ingest adapters."""

    tools: list[ToolSchema]
    adapter: str
    capabilities: IngestCapabilities
    issues: list[IngestIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not any(issue.severity == "blocker" for issue in self.issues)

    def to_dict(self, *, include_tools: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "adapter": self.adapter,
            "tool_count": len(self.tools),
            "ready": self.ready,
            "capabilities": self.capabilities.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": dict(self.metadata),
        }
        if include_tools:
            result["tools"] = [tool.to_dict() for tool in self.tools]
        return result


@runtime_checkable
class IngestAdapter(Protocol):
    """Adapter SPI for API descriptions that can produce ToolSchema objects."""

    name: str
    capabilities: IngestCapabilities

    def detect(self, source: Any) -> float:
        """Return confidence in the inclusive range 0.0..1.0."""

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        """Convert one source into the canonical ingest result."""


class IngestAdapterError(ValueError):
    """Base error for adapter selection and conformance failures."""


class UnknownIngestAdapterError(IngestAdapterError):
    """Raised when no registered adapter can confidently identify a source."""


class AmbiguousIngestAdapterError(IngestAdapterError):
    """Raised when multiple adapters have the same strong detection score."""


class IngestConformanceError(IngestAdapterError):
    """Raised in strict mode when an adapter emits blocker diagnostics."""

    def __init__(self, result: IngestResult):
        self.result = result
        codes = ", ".join(issue.code for issue in result.issues if issue.severity == "blocker")
        super().__init__(f"Ingest result from {result.adapter!r} is blocked: {codes}")


class IngestAdapterRegistry:
    """Thread-safe registry used by applications and third-party source plugins."""

    def __init__(self) -> None:
        self._adapters: dict[str, IngestAdapter] = {}
        self._lock = threading.RLock()

    def register(self, adapter: IngestAdapter, *, replace: bool = False) -> None:
        if not isinstance(adapter, IngestAdapter):
            msg = "adapter must implement name, capabilities, detect(), and ingest()"
            raise TypeError(msg)
        name = str(adapter.name).strip()
        if not name:
            raise ValueError("adapter name must not be empty")
        with self._lock:
            if name in self._adapters and not replace:
                raise ValueError(f"Ingest adapter {name!r} is already registered")
            self._adapters[name] = adapter

    def unregister(self, name: str) -> None:
        with self._lock:
            self._adapters.pop(name, None)

    def get(self, name: str) -> IngestAdapter:
        with self._lock:
            adapter = self._adapters.get(name)
        if adapter is None:
            available = ", ".join(self.names()) or "none"
            raise UnknownIngestAdapterError(
                f"Unknown ingest adapter {name!r}. Registered adapters: {available}"
            )
        return adapter

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))

    def detect(
        self,
        source: Any,
        *,
        minimum_confidence: float = 0.5,
        ambiguity_margin: float = 0.02,
    ) -> tuple[IngestAdapter, float]:
        with self._lock:
            adapters = list(self._adapters.values())
        ranked = sorted(
            ((adapter, _detection_confidence(adapter, source)) for adapter in adapters),
            key=lambda row: (-row[1], row[0].name),
        )
        if not ranked or ranked[0][1] < minimum_confidence:
            available = ", ".join(self.names()) or "none"
            raise UnknownIngestAdapterError(
                "No ingest adapter recognized this source. "
                f"Pass format_hint explicitly or register an adapter. Available: {available}"
            )
        if len(ranked) > 1 and ranked[1][1] >= minimum_confidence:
            if ranked[0][1] - ranked[1][1] <= ambiguity_margin:
                raise AmbiguousIngestAdapterError(
                    "Multiple ingest adapters matched the source: "
                    f"{ranked[0][0].name}={ranked[0][1]:.2f}, "
                    f"{ranked[1][0].name}={ranked[1][1]:.2f}. Pass format_hint explicitly."
                )
        return ranked[0]

    def ingest(
        self,
        source: Any,
        *,
        format_hint: str | None = None,
        required_capabilities: set[str] | None = None,
        strict: bool = False,
        **options: Any,
    ) -> IngestResult:
        if format_hint:
            adapter = self.get(format_hint)
            detection_confidence = None
        else:
            adapter, detection_confidence = self.detect(source)
        result = adapter.ingest(source, **options)
        if result.adapter != adapter.name:
            result.adapter = adapter.name
        if detection_confidence is not None:
            result.metadata.setdefault("detection_confidence", detection_confidence)
        _finalize_result(result, required_capabilities=required_capabilities)
        if strict and not result.ready:
            raise IngestConformanceError(result)
        return result


class OpenAPIIngestAdapter:
    name = "openapi"
    capabilities = IngestCapabilities(
        source_type="openapi",
        features=frozenset(
            {
                "authentication",
                "input_schema",
                "operation_links",
                "output_schema",
                "vendor_extensions",
            }
        ),
        transports=frozenset({"http"}),
        limitations=("callbacks_are_metadata_only", "webhooks_are_not_executable_tools"),
    )

    def detect(self, source: Any) -> float:
        if isinstance(source, dict):
            if "openapi" in source or "swagger" in source:
                return 1.0
            if isinstance(source.get("paths"), dict) and isinstance(source.get("info"), dict):
                return 0.65
            return 0.0
        if isinstance(source, str):
            lowered = source.lower()
            if "openapi" in lowered or "swagger" in lowered:
                return 0.75
        return 0.0

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        from graph_tool_call.ingest.openapi import ingest_openapi

        tools, spec = ingest_openapi(source, **options)
        version = spec.version.value if hasattr(spec.version, "value") else str(spec.version)
        return IngestResult(
            tools=tools,
            adapter=self.name,
            capabilities=self.capabilities,
            metadata={"spec_version": version},
        )


class MCPToolsIngestAdapter:
    name = "mcp-tools"
    capabilities = IngestCapabilities(
        source_type="mcp",
        features=frozenset({"annotations", "input_schema", "server_provenance"}),
        transports=frozenset({"in_process", "json_rpc"}),
        limitations=("output_schema_support_depends_on_upstream_tool_metadata",),
    )

    def detect(self, source: Any) -> float:
        tools = _catalog_rows(source)
        if tools and all(isinstance(row, dict) and "inputSchema" in row for row in tools):
            return 0.98
        return 0.0

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        from graph_tool_call.ingest.mcp import ingest_mcp_tools

        tools = _catalog_rows(source)
        if tools is None:
            raise TypeError("MCP source must be a tool list or a mapping with a tools list")
        server_name = options.pop("server_name", None)
        if options:
            raise TypeError(f"Unsupported MCP ingest options: {', '.join(sorted(options))}")
        return IngestResult(
            tools=ingest_mcp_tools(tools, server_name=server_name),
            adapter=self.name,
            capabilities=self.capabilities,
            metadata={"server_name": server_name} if server_name else {},
        )


class PythonFunctionIngestAdapter:
    name = "python-functions"
    capabilities = IngestCapabilities(
        source_type="python",
        features=frozenset({"input_schema", "local_execution"}),
        transports=frozenset({"in_process"}),
        limitations=("return_schema_depends_on_python_annotations",),
    )

    def detect(self, source: Any) -> float:
        if callable(source):
            return 1.0
        if isinstance(source, (list, tuple)) and source and all(callable(row) for row in source):
            return 0.95
        return 0.0

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        from graph_tool_call.ingest.functions import ingest_function, ingest_functions

        if options:
            raise TypeError(f"Unsupported Python ingest options: {', '.join(sorted(options))}")
        sources = [source] if callable(source) else list(source)
        tools = [ingest_function(source)] if callable(source) else ingest_functions(sources)
        for tool, function in zip(tools, sources, strict=True):
            tool.set_callable(function)
        return IngestResult(
            tools=tools,
            adapter=self.name,
            capabilities=self.capabilities,
        )


class ToolCatalogIngestAdapter:
    name = "tool-catalog"
    capabilities = IngestCapabilities(
        source_type="tool-catalog",
        features=frozenset({"input_schema"}),
        transports=frozenset({"in_process"}),
        limitations=("execution_transport_must_be_supplied_by_the_application",),
    )

    def detect(self, source: Any) -> float:
        tools = _catalog_rows(source)
        if not tools:
            return 0.0
        if all(_looks_like_tool(row) for row in tools):
            return 0.8
        return 0.0

    def ingest(self, source: Any, **options: Any) -> IngestResult:
        if options:
            raise TypeError(f"Unsupported tool catalog options: {', '.join(sorted(options))}")
        rows = _catalog_rows(source)
        if rows is None:
            raise TypeError(
                "tool catalog source must be a tool list or a mapping with a tools list"
            )
        tools = [normalize_tool(parse_tool(row)) for row in rows]
        for tool in tools:
            tool.metadata.setdefault("source", "tool-catalog")
        return IngestResult(
            tools=tools,
            adapter=self.name,
            capabilities=self.capabilities,
        )


def _catalog_rows(source: Any) -> list[dict[str, Any]] | None:
    if isinstance(source, list) and all(isinstance(row, dict) for row in source):
        return source
    if isinstance(source, dict) and isinstance(source.get("tools"), list):
        rows = source["tools"]
        if all(isinstance(row, dict) for row in rows):
            return rows
    return None


def _looks_like_tool(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if isinstance(row.get("function"), dict):
        return bool(row["function"].get("name"))
    return bool(row.get("name")) and any(
        key in row for key in ("parameters", "input_schema", "inputSchema")
    )


def _detection_confidence(adapter: IngestAdapter, source: Any) -> float:
    try:
        confidence = float(adapter.detect(source))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, confidence))


def _finalize_result(
    result: IngestResult,
    *,
    required_capabilities: set[str] | None,
) -> None:
    canonical_tools: list[ToolSchema] = []
    for index, tool in enumerate(result.tools):
        if not isinstance(tool, ToolSchema):
            result.issues.append(
                IngestIssue(
                    severity="blocker",
                    code="invalid_tool_schema",
                    message="Adapters must return ToolSchema instances.",
                    evidence={"index": index, "actual_type": type(tool).__name__},
                )
            )
            continue
        if not tool.name.strip():
            result.issues.append(
                IngestIssue(
                    severity="blocker",
                    code="invalid_tool_name",
                    message="Canonical tool names must not be empty.",
                    evidence={"index": index},
                )
            )
            continue
        canonical_tools.append(tool)
    result.tools = canonical_tools

    if not result.tools:
        result.issues.append(
            IngestIssue(
                severity="blocker",
                code="empty_tool_catalog",
                message="The adapter did not produce any tools.",
            )
        )

    names: set[str] = set()
    duplicates: set[str] = set()
    for tool in result.tools:
        if tool.name in names:
            duplicates.add(tool.name)
        names.add(tool.name)
        if not tool.description.strip():
            result.issues.append(
                IngestIssue(
                    severity="warning",
                    code="missing_tool_description",
                    message="Tool description is empty; semantic retrieval may be weaker.",
                    tool=tool.name,
                )
            )
        ingest_metadata = tool.metadata.setdefault("ingest", {})
        ingest_metadata.setdefault("adapter", result.adapter)
        ingest_metadata.setdefault("source_type", result.capabilities.source_type)
        ingest_metadata.setdefault("capabilities", sorted(result.capabilities.features))

    for name in sorted(duplicates):
        result.issues.append(
            IngestIssue(
                severity="blocker",
                code="duplicate_tool_name",
                message="Tool names must be unique within one canonical catalog.",
                tool=name,
            )
        )

    missing = sorted((required_capabilities or set()) - result.capabilities.features)
    for capability in missing:
        result.issues.append(
            IngestIssue(
                severity="blocker",
                code="unsupported_capability",
                message=f"The selected adapter cannot guarantee capability {capability!r}.",
                evidence={
                    "capability": capability,
                    "adapter": result.adapter,
                    "available": sorted(result.capabilities.features),
                },
            )
        )


def _build_default_registry() -> IngestAdapterRegistry:
    registry = IngestAdapterRegistry()
    registry.register(OpenAPIIngestAdapter())
    registry.register(MCPToolsIngestAdapter())
    registry.register(PythonFunctionIngestAdapter())
    registry.register(ToolCatalogIngestAdapter())
    return registry


_DEFAULT_REGISTRY = _build_default_registry()


def get_default_ingest_registry() -> IngestAdapterRegistry:
    return _DEFAULT_REGISTRY


def register_ingest_adapter(adapter: IngestAdapter, *, replace: bool = False) -> None:
    _DEFAULT_REGISTRY.register(adapter, replace=replace)


def unregister_ingest_adapter(name: str) -> None:
    _DEFAULT_REGISTRY.unregister(name)


def detect_ingest_adapter(source: Any) -> tuple[IngestAdapter, float]:
    return _DEFAULT_REGISTRY.detect(source)


def ingest_source(
    source: Any,
    *,
    format_hint: str | None = None,
    required_capabilities: set[str] | None = None,
    strict: bool = False,
    **options: Any,
) -> IngestResult:
    """Ingest a source through auto-detection or an explicitly named adapter."""

    return _DEFAULT_REGISTRY.ingest(
        source,
        format_hint=format_hint,
        required_capabilities=required_capabilities,
        strict=strict,
        **options,
    )


__all__ = [
    "AmbiguousIngestAdapterError",
    "IngestAdapter",
    "IngestAdapterError",
    "IngestAdapterRegistry",
    "IngestCapabilities",
    "IngestConformanceError",
    "IngestIssue",
    "IngestResult",
    "UnknownIngestAdapterError",
    "detect_ingest_adapter",
    "get_default_ingest_registry",
    "ingest_source",
    "register_ingest_adapter",
    "unregister_ingest_adapter",
]
