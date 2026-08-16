"""Ingest Arazzo workflow descriptions into tool graph relations."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
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
    source_step: str = ""
    target_step: str = ""
    dependency_kind: str = "sequential"
    bindings: tuple[dict[str, Any], ...] = ()


_STEP_OUTPUT_RE = re.compile(r"\$steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9._-]+)(#[^\s\"'}]+)?")
_WORKFLOW_STEP_OUTPUT_RE = re.compile(
    r"\$workflows\.([A-Za-z0-9_-]+)\.steps\.([A-Za-z0-9_-]+)\.outputs\."
    r"([A-Za-z0-9._-]+)(#[^\s\"'}]+)?"
)


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
        return _parse_spec_text(text)

    path = Path(source)
    text = path.read_text(encoding="utf-8")

    return _parse_spec_text(text, prefer_yaml=path.suffix in (".yaml", ".yml"))


def _parse_spec_text(text: str, *, prefer_yaml: bool = False) -> dict[str, Any]:
    if not prefer_yaml:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
    if not _HAS_YAML:
        raise ImportError(
            "PyYAML is required for YAML Arazzo descriptions. "
            "Install with: pip install graph-tool-call[openapi]"
        )
    value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("Arazzo description must be a JSON/YAML object")
    return value


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_operation_id(
    step: dict[str, Any],
    operation_resolver: Callable[[dict[str, Any]], str | None] | None = None,
) -> str | None:
    """Extract operationId from an Arazzo step."""
    if operation_resolver is not None and (resolved := operation_resolver(step)):
        return resolved
    # Direct operationId reference
    if "operationId" in step:
        operation_id = str(step["operationId"] or "").strip()
        if operation_id.startswith("$sourceDescriptions."):
            return operation_id.rsplit(".", 1)[-1]
        return operation_id or None
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
    operation_resolver: Callable[[dict[str, Any]], str | None] | None = None,
) -> list[ArazzoRelation]:
    """Parse an Arazzo spec and extract workflow dependencies as PRECEDES relations.

    Arazzo 1.0 and 1.1 ordering constructs are accepted. Explicit
    ``dependsOn`` and runtime output references outrank implicit sequential
    step order when they describe the same operation pair.

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

    workflows = [row for row in spec.get("workflows", []) if isinstance(row, dict)]
    workflow_steps: dict[str, dict[str, dict[str, Any]]] = {}
    workflow_order: dict[str, list[str]] = {}
    for workflow in workflows:
        workflow_id = str(workflow.get("workflowId") or "unknown")
        step_rows: dict[str, dict[str, Any]] = {}
        ordered_ids: list[str] = []
        for step in workflow.get("steps") or []:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("stepId") or "").strip()
            operation_id = _extract_operation_id(step, operation_resolver)
            if not step_id or not operation_id:
                continue
            step_rows[step_id] = {
                "step": step,
                "operation_id": operation_id,
                "outputs": step.get("outputs") if isinstance(step.get("outputs"), dict) else {},
            }
            ordered_ids.append(step_id)
        workflow_steps[workflow_id] = step_rows
        workflow_order[workflow_id] = ordered_ids

    for workflow in workflows:
        workflow_id = str(workflow.get("workflowId") or "unknown")
        step_rows = workflow_steps.get(workflow_id, {})
        ordered_ids = workflow_order.get(workflow_id, [])
        pending: dict[tuple[str, str], dict[str, Any]] = {}

        for target_step_id in ordered_ids:
            target_row = step_rows[target_step_id]
            target_step = target_row["step"]
            for dependency in target_step.get("dependsOn") or []:
                source_ref = _resolve_step_reference(
                    str(dependency),
                    current_workflow=workflow_id,
                    workflow_steps=workflow_steps,
                )
                if source_ref:
                    _record_dependency(
                        pending,
                        source_ref=source_ref,
                        target_ref=(workflow_id, target_step_id),
                        dependency_kind="depends_on",
                    )

            for binding in _runtime_step_bindings(
                target_step,
                current_workflow=workflow_id,
                workflow_steps=workflow_steps,
            ):
                source_ref = (binding.pop("source_workflow"), binding["source_step_id"])
                _record_dependency(
                    pending,
                    source_ref=source_ref,
                    target_ref=(workflow_id, target_step_id),
                    dependency_kind="runtime_reference",
                    binding=binding,
                )

        for source_step_id, target_step_id in zip(ordered_ids, ordered_ids[1:]):
            _record_dependency(
                pending,
                source_ref=(workflow_id, source_step_id),
                target_ref=(workflow_id, target_step_id),
                dependency_kind="sequential",
            )

        for row in pending.values():
            source_workflow, source_step_id = row["source_ref"]
            target_workflow, target_step_id = row["target_ref"]
            source_row = workflow_steps.get(source_workflow, {}).get(source_step_id)
            target_row = workflow_steps.get(target_workflow, {}).get(target_step_id)
            if not source_row or not target_row:
                continue
            source_op = str(source_row["operation_id"])
            target_op = str(target_row["operation_id"])
            if source_op == target_op:
                continue
            if registered_tools is not None and (
                source_op not in registered_tools or target_op not in registered_tools
            ):
                continue
            relations.append(
                ArazzoRelation(
                    source=source_op,
                    target=target_op,
                    workflow=target_workflow,
                    source_step=source_step_id,
                    target_step=target_step_id,
                    dependency_kind=str(row["dependency_kind"]),
                    bindings=tuple(row["bindings"]),
                )
            )

    return relations


def _record_dependency(
    pending: dict[tuple[str, str], dict[str, Any]],
    *,
    source_ref: tuple[str, str],
    target_ref: tuple[str, str],
    dependency_kind: str,
    binding: dict[str, Any] | None = None,
) -> None:
    if source_ref == target_ref:
        return
    key = ("::".join(source_ref), "::".join(target_ref))
    row = pending.setdefault(
        key,
        {
            "source_ref": source_ref,
            "target_ref": target_ref,
            "dependency_kind": dependency_kind,
            "bindings": [],
        },
    )
    rank = {"sequential": 1, "depends_on": 2, "runtime_reference": 3}
    if rank.get(dependency_kind, 0) > rank.get(str(row["dependency_kind"]), 0):
        row["dependency_kind"] = dependency_kind
    if binding and binding not in row["bindings"]:
        row["bindings"].append(binding)


def _resolve_step_reference(
    value: str,
    *,
    current_workflow: str,
    workflow_steps: dict[str, dict[str, dict[str, Any]]],
) -> tuple[str, str] | None:
    text = value.strip()
    if text in workflow_steps.get(current_workflow, {}):
        return current_workflow, text
    match = re.search(r"\$workflows\.([A-Za-z0-9_-]+)\.steps\.([A-Za-z0-9_-]+)", text)
    if match and match.group(2) in workflow_steps.get(match.group(1), {}):
        return match.group(1), match.group(2)
    return None


def _runtime_step_bindings(
    step: dict[str, Any],
    *,
    current_workflow: str,
    workflow_steps: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    parameter_values = step.get("parameters") or []
    if isinstance(parameter_values, list):
        for parameter in parameter_values:
            if not isinstance(parameter, dict):
                continue
            _collect_runtime_bindings(
                parameter.get("value"),
                target_field=str(parameter.get("name") or ""),
                target_location=str(parameter.get("in") or "parameter"),
                current_workflow=current_workflow,
                workflow_steps=workflow_steps,
                bindings=bindings,
            )
    request_body = step.get("requestBody")
    if isinstance(request_body, dict):
        _walk_request_body_bindings(
            request_body,
            path="requestBody",
            current_workflow=current_workflow,
            workflow_steps=workflow_steps,
            bindings=bindings,
        )
    return bindings


def _walk_request_body_bindings(
    value: Any,
    *,
    path: str,
    current_workflow: str,
    workflow_steps: dict[str, dict[str, dict[str, Any]]],
    bindings: list[dict[str, Any]],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_request_body_bindings(
                item,
                path=f"{path}.{key}",
                current_workflow=current_workflow,
                workflow_steps=workflow_steps,
                bindings=bindings,
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_request_body_bindings(
                item,
                path=f"{path}[{index}]",
                current_workflow=current_workflow,
                workflow_steps=workflow_steps,
                bindings=bindings,
            )
        return
    _collect_runtime_bindings(
        value,
        target_field=_request_body_target_field(path),
        target_location="request_body",
        target_path=path,
        current_workflow=current_workflow,
        workflow_steps=workflow_steps,
        bindings=bindings,
    )


def _collect_runtime_bindings(
    value: Any,
    *,
    target_field: str,
    target_location: str,
    target_path: str = "",
    current_workflow: str,
    workflow_steps: dict[str, dict[str, dict[str, Any]]],
    bindings: list[dict[str, Any]],
) -> None:
    if not isinstance(value, str):
        return
    matches: list[tuple[str, str, str, str, str]] = []
    matches.extend(
        (
            current_workflow,
            match.group(1),
            match.group(2),
            match.group(3) or "",
            match.group(0),
        )
        for match in _STEP_OUTPUT_RE.finditer(value)
    )
    matches.extend(
        (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4) or "",
            match.group(0),
        )
        for match in _WORKFLOW_STEP_OUTPUT_RE.finditer(value)
    )
    for source_workflow, source_step_id, source_output, suffix, expression in matches:
        source_row = workflow_steps.get(source_workflow, {}).get(source_step_id)
        if not source_row:
            continue
        output_expression = source_row["outputs"].get(source_output)
        source_path = _response_expression_path(output_expression, suffix=suffix)
        binding = {
            "source_workflow": source_workflow,
            "source_step_id": source_step_id,
            "source_output": source_output,
            "source_path": source_path,
            "target_field": target_field,
            "target_location": target_location,
            "expression": expression,
            **({"target_path": target_path} if target_path else {}),
        }
        if binding not in bindings:
            bindings.append(binding)


def _request_body_target_field(path: str) -> str:
    segments = [segment for segment in re.split(r"\.|\[\d+\]", path) if segment]
    for segment in reversed(segments):
        if segment not in {"requestBody", "payload", "contentType", "replacements"}:
            return segment
    return ""


def _response_expression_path(value: Any, *, suffix: str = "") -> str:
    expression = str(value or "").strip()
    if expression.startswith("$response.body"):
        base = _json_pointer_to_json_path(expression.removeprefix("$response.body"))
    elif expression.startswith("$response.header."):
        base = f"$.headers.{expression.removeprefix('$response.header.')}"
    elif expression.startswith("$message.payload"):
        payload_path = _json_pointer_to_json_path(expression.removeprefix("$message.payload"))
        base = "$.payload" + (payload_path[1:] if payload_path != "$" else "")
    else:
        base = ""
    if suffix and base:
        suffix_path = _json_pointer_to_json_path(suffix)
        if suffix_path != "$":
            base += suffix_path[1:]
    return base


def _json_pointer_to_json_path(pointer: str) -> str:
    value = str(pointer or "")
    if value.startswith("#"):
        value = value[1:]
    if not value:
        return "$"
    path = "$"
    for segment in value.lstrip("/").split("/"):
        decoded = segment.replace("~1", "/").replace("~0", "~")
        path += f"[{decoded}]" if decoded.isdigit() else f".{decoded}"
    return path
