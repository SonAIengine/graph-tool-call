"""Ingest layer: parse external tool specs into ToolSchema."""

from graph_tool_call.ingest.adapters import (
    AmbiguousIngestAdapterError,
    IngestAdapter,
    IngestAdapterError,
    IngestAdapterRegistry,
    IngestCapabilities,
    IngestConformanceError,
    IngestIssue,
    IngestResult,
    UnknownIngestAdapterError,
    detect_ingest_adapter,
    get_default_ingest_registry,
    ingest_source,
    register_ingest_adapter,
    unregister_ingest_adapter,
)
from graph_tool_call.ingest.arazzo import ArazzoRelation, ingest_arazzo
from graph_tool_call.ingest.functions import ingest_function, ingest_functions
from graph_tool_call.ingest.normalizer import NormalizedSpec, SpecVersion, normalize
from graph_tool_call.ingest.openapi import ingest_openapi

__all__ = [
    "ArazzoRelation",
    "AmbiguousIngestAdapterError",
    "IngestAdapter",
    "IngestAdapterError",
    "IngestAdapterRegistry",
    "IngestCapabilities",
    "IngestConformanceError",
    "IngestIssue",
    "IngestResult",
    "NormalizedSpec",
    "SpecVersion",
    "UnknownIngestAdapterError",
    "detect_ingest_adapter",
    "get_default_ingest_registry",
    "ingest_arazzo",
    "ingest_function",
    "ingest_functions",
    "ingest_openapi",
    "ingest_source",
    "normalize",
    "register_ingest_adapter",
    "unregister_ingest_adapter",
]
