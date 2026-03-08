"""Tool call validation and auto-correction.

Validates LLM-generated tool calls against the registered tool graph
and provides corrections without requiring an additional LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from graph_tool_call.core.tool import ToolSchema


@dataclass
class ValidationResult:
    """Result of validating a tool call.

    Attributes
    ----------
    valid:
        True if the tool call is correct as-is.
    tool_name:
        The corrected tool name (or original if valid).
    arguments:
        The corrected arguments dict (or original if valid).
    errors:
        List of error descriptions.
    corrections:
        Dict of field -> (original, corrected) for applied corrections.
    warnings:
        List of non-blocking warnings (e.g. destructive operation).
    """

    valid: bool = True
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    corrections: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def validate_tool_call(
    call: dict[str, Any],
    tools: dict[str, ToolSchema],
    *,
    fuzzy_threshold: float = 0.7,
) -> ValidationResult:
    """Validate and auto-correct a tool call against registered tools.

    Parameters
    ----------
    call:
        Tool call dict. Supports formats:
        - ``{"name": "toolName", "arguments": {...}}``
        - ``{"function": {"name": "toolName", "arguments": {...}}}``
    tools:
        Registered tools from ``ToolGraph.tools``.
    fuzzy_threshold:
        Minimum similarity for fuzzy name matching (0.0-1.0).

    Returns
    -------
    ValidationResult
        Contains corrected name/arguments, error list, and warnings.
    """
    result = ValidationResult()

    # --- Extract name and arguments ---
    if "function" in call:
        func = call["function"]
        raw_name = func.get("name", "")
        raw_args = func.get("arguments", {})
    else:
        raw_name = call.get("name", "")
        raw_args = call.get("arguments", call.get("parameters", {}))

    if isinstance(raw_args, str):
        import json

        try:
            raw_args = json.loads(raw_args)
        except (json.JSONDecodeError, ValueError):
            result.valid = False
            result.errors.append(f"arguments is not valid JSON: {raw_args!r}")
            raw_args = {}

    result.tool_name = raw_name
    result.arguments = dict(raw_args) if raw_args else {}

    if not raw_name:
        result.valid = False
        result.errors.append("tool name is empty")
        return result

    # --- Tool name validation ---
    matched_name = _match_tool_name(raw_name, tools, fuzzy_threshold)

    if matched_name is None:
        result.valid = False
        result.errors.append(f"unknown tool: '{raw_name}'")
        # Suggest closest matches
        suggestions = _find_similar_names(raw_name, tools, top_k=3)
        if suggestions:
            result.errors.append(f"did you mean: {', '.join(suggestions)}?")
        return result

    if matched_name != raw_name:
        result.corrections["name"] = (raw_name, matched_name)
        result.valid = False
    result.tool_name = matched_name

    tool = tools[matched_name]

    # --- Parameter validation ---
    _validate_params(tool, result)

    # --- Annotation warnings ---
    if tool.annotations is not None:
        if tool.annotations.destructive_hint:
            result.warnings.append("destructive operation — confirm before executing")
        if tool.annotations.read_only_hint is False and tool.annotations.idempotent_hint is False:
            result.warnings.append("non-idempotent write — may create duplicates if retried")

    return result


def _match_tool_name(
    raw_name: str,
    tools: dict[str, ToolSchema],
    threshold: float,
) -> str | None:
    """Match tool name with exact, case-insensitive, and fuzzy matching."""
    # Exact match
    if raw_name in tools:
        return raw_name

    # Case-insensitive match
    lower_map = {name.lower(): name for name in tools}
    if raw_name.lower() in lower_map:
        return lower_map[raw_name.lower()]

    # Fuzzy match
    best_score = 0.0
    best_name: str | None = None
    for name in tools:
        score = SequenceMatcher(None, raw_name.lower(), name.lower()).ratio()
        if score > best_score:
            best_score = score
            best_name = name

    if best_name and best_score >= threshold:
        return best_name

    return None


def _find_similar_names(
    raw_name: str,
    tools: dict[str, ToolSchema],
    top_k: int = 3,
) -> list[str]:
    """Find the most similar tool names for error messages."""
    scored = []
    for name in tools:
        score = SequenceMatcher(None, raw_name.lower(), name.lower()).ratio()
        scored.append((name, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [name for name, score in scored[:top_k] if score > 0.3]


def _validate_params(tool: ToolSchema, result: ValidationResult) -> None:
    """Validate and correct parameters."""
    if not tool.parameters:
        return

    param_map = {p.name: p for p in tool.parameters}
    param_lower_map = {p.name.lower(): p.name for p in tool.parameters}

    # Check for missing required params
    for param in tool.parameters:
        if param.required and param.name not in result.arguments:
            # Try case-insensitive match
            found = False
            for arg_key in list(result.arguments.keys()):
                if arg_key.lower() == param.name.lower():
                    val = result.arguments.pop(arg_key)
                    result.arguments[param.name] = val
                    result.corrections[f"param:{arg_key}"] = (arg_key, param.name)
                    result.valid = False
                    found = True
                    break
            if not found:
                result.valid = False
                result.errors.append(f"missing required parameter: '{param.name}'")

    # Check for unknown params (try fuzzy correction)
    known_names = set(param_map.keys())
    for arg_key in list(result.arguments.keys()):
        if arg_key in known_names:
            continue
        # Case-insensitive
        if arg_key.lower() in param_lower_map:
            correct_name = param_lower_map[arg_key.lower()]
            val = result.arguments.pop(arg_key)
            result.arguments[correct_name] = val
            result.corrections[f"param:{arg_key}"] = (arg_key, correct_name)
            result.valid = False
            continue
        # Fuzzy match
        best_score = 0.0
        best_param: str | None = None
        for pname in known_names:
            score = SequenceMatcher(None, arg_key.lower(), pname.lower()).ratio()
            if score > best_score:
                best_score = score
                best_param = pname
        if best_param and best_score >= 0.7:
            val = result.arguments.pop(arg_key)
            result.arguments[best_param] = val
            result.corrections[f"param:{arg_key}"] = (arg_key, best_param)
            result.valid = False
        else:
            result.warnings.append(f"unknown parameter: '{arg_key}'")

    # Validate enum values
    for arg_key, arg_val in result.arguments.items():
        if arg_key in param_map and param_map[arg_key].enum:
            allowed = param_map[arg_key].enum
            if isinstance(arg_val, str) and arg_val not in allowed:
                # Case-insensitive enum match
                lower_enum = {v.lower(): v for v in allowed}
                if arg_val.lower() in lower_enum:
                    corrected = lower_enum[arg_val.lower()]
                    result.arguments[arg_key] = corrected
                    result.corrections[f"enum:{arg_key}"] = (arg_val, corrected)
                    result.valid = False
                else:
                    result.errors.append(
                        f"invalid value for '{arg_key}': '{arg_val}'. Allowed: {allowed}"
                    )
                    result.valid = False
