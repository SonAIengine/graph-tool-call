"""Ingest Arazzo 1.0.0 workflow specifications into tool graph relations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph_tool_call.net import fetch_url_text
from graph_tool_call.ontology.schema import RelationType

# ---------------------------------------------------------------------------
# YAML support (optional)
# ---------------------------------------------------------------------------

try:
    import yaml  # type: ignore[import-untyped]

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@dataclass
class ArazzoRelation:
    """A workflow-derived relation between two operations."""

    source: str  # operationId that must run first
    target: str  # operationId that depends on source
    workflow: str  # workflow name
    relation_type: RelationType = RelationType.PRECEDES


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

_HTTP_PREFIXES = ("http://", "https://")


def _load_spec(
    source: dict[str, Any] | str,
    *,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Load an Arazzo spec from a dict, file path, or URL."""
    if isinstance(source, dict):
        return source

    if isinstance(source, str) and source.startswith(_HTTP_PREFIXES):
        text = fetch_url_text(
            source,
            headers={"Accept": "application/json"},
            timeout=30,
            allow_private_hosts=allow_private_hosts,
            max_response_bytes=max_response_bytes,
        )
        return json.loads(text)

    path = Path(source)
    text = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            raise ImportError(
                "PyYAML is required for YAML files. "
                "Install with: pip install graph-tool-call[openapi]"
            )
        return yaml.safe_load(text)

    return json.loads(text)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_operation_id(step: dict[str, Any]) -> str | None:
    """Extract operationId from an Arazzo step."""
    # Direct operationId reference
    if "operationId" in step:
        return step["operationId"]
    # operationPath format: "{sourceDescription}#{jsonPointer}" or just operationId
    if "operationPath" in step:
        op_path = step["operationPath"]
        if "#" in op_path:
            # Format: "{sourceDescription}#/paths/~1pets/get" — not an operationId
            return None
        return op_path
    return None


def ingest_arazzo(
    source: dict[str, Any] | str,
    *,
    registered_tools: set[str] | None = None,
    allow_private_hosts: bool = False,
    max_response_bytes: int = 5_000_000,
) -> list[ArazzoRelation]:
    """Parse an Arazzo 1.0.0 spec and extract workflow step dependencies as PRECEDES relations.

    Parameters
    ----------
    source:
        An Arazzo spec dict, file path, or URL.
    registered_tools:
        If provided, only emit relations for operationIds in this set.
        If None, emit all relations.

    Returns
    -------
    list[ArazzoRelation]
        Detected PRECEDES relations from workflow step dependencies.
    """
    spec = _load_spec(
        source,
        allow_private_hosts=allow_private_hosts,
        max_response_bytes=max_response_bytes,
    )
    relations: list[ArazzoRelation] = []

    workflows = spec.get("workflows", [])
    for workflow in workflows:
        wf_name = workflow.get("workflowId", "unknown")
        steps = workflow.get("steps", [])

        # Build step_id → operationId mapping
        step_ops: dict[str, str] = {}
        for step in steps:
            step_id = step.get("stepId", "")
            op_id = _extract_operation_id(step)
            if step_id and op_id:
                step_ops[step_id] = op_id

        # Extract dependsOn → PRECEDES relations
        for step in steps:
            step_id = step.get("stepId", "")
            target_op = step_ops.get(step_id)
            if not target_op:
                continue

            depends_on = step.get("dependsOn", [])
            for dep_step_id in depends_on:
                source_op = step_ops.get(dep_step_id)
                if not source_op:
                    continue
                if source_op == target_op:
                    continue

                # Filter by registered tools if provided
                if registered_tools is not None:
                    if source_op not in registered_tools or target_op not in registered_tools:
                        continue

                relations.append(
                    ArazzoRelation(
                        source=source_op,
                        target=target_op,
                        workflow=wf_name,
                    )
                )

        # Sequential step ordering (implicit): each step PRECEDES the next
        ordered_ops: list[str] = []
        for step in steps:
            step_id = step.get("stepId", "")
            op_id = step_ops.get(step_id)
            if op_id:
                ordered_ops.append(op_id)

        for i in range(len(ordered_ops) - 1):
            src, tgt = ordered_ops[i], ordered_ops[i + 1]
            if src == tgt:
                continue
            if registered_tools is not None:
                if src not in registered_tools or tgt not in registered_tools:
                    continue

            # Only add if not already captured by dependsOn
            already = any(
                r.source == src and r.target == tgt and r.workflow == wf_name for r in relations
            )
            if not already:
                relations.append(ArazzoRelation(source=src, target=tgt, workflow=wf_name))

    return relations
