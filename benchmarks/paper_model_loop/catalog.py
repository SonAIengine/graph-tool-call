"""Frozen selection-catalog and full-schema hydration contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from benchmarks.paper_baselines.token_budget import (
    TokenCounter,
    contract_projected_model_facing_schema,
    model_facing_schema,
    serialize_model_facing_payloads,
)
from graph_tool_call.core.tool import ToolParameter, ToolSchema

B6B_BASELINE = "graph_consumer_aligned_admission"
B6C_BASELINE = "graph_budget_aware_schema_admission"
MODEL_LOOP_BASELINES = (B6B_BASELINE, B6C_BASELINE)
SELECTION_PROTOCOL_REVISION = "paper-two-pass-tool-selection-v1"
HYDRATION_POLICY_REVISION = "paper-full-schema-hydration-v1"
PLAN_VALIDATION_POLICY_REVISION = "paper-plan-schema-validation-v1"
PLANNING_CONTRACT_VIEW_REVISION = "paper-hydrated-contract-view-v1"
MAX_PLANNING_PRODUCES_PER_TOOL = 32


@dataclass(frozen=True)
class SelectionCatalog:
    """One exact model-facing candidate catalog reconstructed from an artifact."""

    baseline: str
    ranked_names: list[str]
    selected_names: list[str]
    payloads: list[dict[str, Any]]
    schema_modes: dict[str, str]
    serialized: str
    schema_tokens: int
    token_budget_limit: int
    catalog_sha256: str

    def to_dict(self, *, include_payloads: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if not include_payloads:
            value.pop("payloads", None)
            value.pop("serialized", None)
        return value


@dataclass(frozen=True)
class HydratedCatalog:
    """Complete schemas loaded after selection and before plan generation."""

    requested_names: list[str]
    hydrated_names: list[str]
    missing_names: list[str]
    payloads: list[dict[str, Any]]
    schema_sha256: dict[str, str]
    source_schema_sha256: dict[str, str]
    catalog_sha256: str

    @property
    def success(self) -> bool:
        return not self.missing_names and self.requested_names == self.hydrated_names

    def to_dict(self, *, include_payloads: bool = False) -> dict[str, Any]:
        value = asdict(self)
        value["success"] = self.success
        if not include_payloads:
            value.pop("payloads", None)
        return value


@dataclass(frozen=True)
class SelectorDecision:
    """Normalized first-pass model decision."""

    target_tool: str
    supporting_tools: list[str]
    selected_tools: list[str]
    raw: dict[str, Any]
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanValidation:
    """Structural validation of a plan generated from hydrated schemas."""

    final_target: str
    plan_tools: list[str]
    plan_tool_validity: float
    argument_schema_validity: float
    required_input_accounting: float
    final_target_consistency: float
    valid: bool
    reason_codes: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_paired_case_contract(case: dict[str, Any]) -> dict[str, Any]:
    """Verify that B6c changes schema admission only, never ranking."""
    observed = case.get("observed") or {}
    budget_observed = case.get("token_budget_observed") or {}
    b6b_ranked = list((observed.get(B6B_BASELINE) or {}).get("retrieved") or [])
    b6c_ranked = list((observed.get(B6C_BASELINE) or {}).get("retrieved") or [])
    if not b6b_ranked or b6b_ranked != b6c_ranked:
        raise ValueError("B6b and B6c must expose the same frozen ranking.")

    admission = (
        ((observed.get(B6B_BASELINE) or {}).get("diagnostics") or {})
        .get("candidate_admission", {})
        .get("admitted", [])
    )
    admitted_names = {
        str(row.get("name") or "") for row in admission if isinstance(row, dict) and row.get("name")
    }
    schema_modes = dict((budget_observed.get(B6C_BASELINE) or {}).get("schema_modes") or {})
    projected_names = {name for name, mode in schema_modes.items() if mode == "contract_projected"}
    if not projected_names.issubset(admitted_names):
        raise ValueError("B6c projected schemas must be justified by B6b admission evidence.")

    return {
        "ranking_identical": True,
        "admitted_names": sorted(admitted_names),
        "projected_names": sorted(projected_names),
        "projection_evidence_valid": True,
    }


def build_selection_catalog(
    case: dict[str, Any],
    tools_by_name: dict[str, ToolSchema],
    *,
    baseline: str,
    token_counter: TokenCounter,
) -> SelectionCatalog:
    """Reconstruct an exact B6b or B6c model-facing catalog."""
    if baseline not in MODEL_LOOP_BASELINES:
        raise ValueError(f"Unsupported model-loop baseline: {baseline}")
    validate_paired_case_contract(case)
    observed = case["observed"][baseline]
    budget_observed = case["token_budget_observed"][baseline]
    ranked_names = [str(name) for name in observed.get("retrieved") or []]
    selected_names = [str(name) for name in budget_observed.get("retrieved") or []]
    unknown_names = [name for name in selected_names if name not in tools_by_name]
    if unknown_names:
        raise ValueError(f"Catalog references missing tools: {', '.join(unknown_names)}")

    raw_modes = dict(budget_observed.get("schema_modes") or {})
    schema_modes = {name: str(raw_modes.get(name) or "full") for name in selected_names}
    invalid_modes = sorted(set(schema_modes.values()) - {"full", "contract_projected"})
    if invalid_modes:
        raise ValueError(f"Unsupported schema modes: {', '.join(invalid_modes)}")
    if baseline == B6B_BASELINE and any(mode != "full" for mode in schema_modes.values()):
        raise ValueError("B6b selection catalogs must contain only complete schemas.")

    payloads = [
        (
            contract_projected_model_facing_schema(tools_by_name[name])
            if schema_modes[name] == "contract_projected"
            else model_facing_schema(tools_by_name[name])
        )
        for name in selected_names
    ]
    serialized = serialize_model_facing_payloads(payloads)
    schema_tokens = token_counter.count(serialized)
    token_budget_limit = int(budget_observed.get("token_budget_limit") or 0)
    if token_budget_limit <= 0 or schema_tokens > token_budget_limit:
        raise ValueError("Selection catalog exceeds its frozen token budget.")
    recorded_tokens = int(budget_observed.get("schema_tokens") or 0)
    if recorded_tokens and recorded_tokens != schema_tokens:
        raise ValueError(
            f"Selection catalog token count changed: recorded={recorded_tokens}, "
            f"reconstructed={schema_tokens}"
        )

    return SelectionCatalog(
        baseline=baseline,
        ranked_names=ranked_names,
        selected_names=selected_names,
        payloads=payloads,
        schema_modes=schema_modes,
        serialized=serialized,
        schema_tokens=schema_tokens,
        token_budget_limit=token_budget_limit,
        catalog_sha256=_sha256_text(serialized),
    )


def hydrate_full_schemas(
    names: list[str],
    tools_by_name: dict[str, ToolSchema],
) -> HydratedCatalog:
    """Load canonical complete schemas for a model-selected tool set."""
    requested_names = _dedupe_names(names)
    hydrated_names = [name for name in requested_names if name in tools_by_name]
    missing_names = [name for name in requested_names if name not in tools_by_name]
    payloads = [model_facing_schema(tools_by_name[name]) for name in hydrated_names]
    hashes = {
        name: _sha256_text(serialize_model_facing_payloads([payload]))
        for name, payload in zip(hydrated_names, payloads, strict=True)
    }
    source_hashes = {
        name: _sha256_text(_canonical_json(tools_by_name[name].to_dict()))
        for name in hydrated_names
    }
    serialized = serialize_model_facing_payloads(payloads)
    return HydratedCatalog(
        requested_names=requested_names,
        hydrated_names=hydrated_names,
        missing_names=missing_names,
        payloads=payloads,
        schema_sha256=hashes,
        source_schema_sha256=source_hashes,
        catalog_sha256=_sha256_text(serialized),
    )


def build_planning_contract_view(
    hydrated: HydratedCatalog,
    tools_by_name: dict[str, ToolSchema],
) -> list[dict[str, Any]]:
    """Project hydrated source contracts to fields relevant within the selected set."""
    selected_tools = [
        tools_by_name[name] for name in hydrated.hydrated_names if name in tools_by_name
    ]
    consumer_names = {
        str(row.get("field_name") or "")
        for tool in selected_tools
        for row in (tool.metadata.get("api_contract") or {}).get("consumes") or []
        if row.get("kind") not in {"auth", "context"} and row.get("field_name")
    }
    consumer_names.update(
        parameter.name for tool in selected_tools for parameter in tool.parameters
    )
    result = []
    for tool in selected_tools:
        contract = tool.metadata.get("api_contract") or {}
        consumes = [
            _compact_contract_row(row)
            for row in contract.get("consumes") or []
            if row.get("kind") not in {"auth", "context"}
        ]
        produces = []
        seen_produces: set[tuple[str, str]] = set()
        for row in contract.get("produces") or []:
            field_name = str(row.get("field_name") or "")
            if not field_name or not any(
                _field_names_compatible(field_name, consumer_name)
                for consumer_name in consumer_names
            ):
                continue
            key = (field_name, str(row.get("json_path") or ""))
            if key in seen_produces:
                continue
            seen_produces.add(key)
            produces.append(_compact_contract_row(row))
            if len(produces) >= MAX_PLANNING_PRODUCES_PER_TOOL:
                break
        result.append(
            {
                **model_facing_schema(tool),
                "method": tool.metadata.get("method"),
                "path": tool.metadata.get("path"),
                "api_contract": {
                    "consumes": consumes,
                    "produces": produces,
                },
                "source_schema_sha256": hydrated.source_schema_sha256[tool.name],
            }
        )
    return result


def parse_selector_decision(content: str) -> SelectorDecision:
    """Parse the first-pass JSON decision without accepting free-form tool names."""
    payload = extract_json_object(content)
    target = str(payload.get("target_tool") or payload.get("target") or "").strip()
    supporting = payload.get("supporting_tools")
    if supporting is None:
        supporting = payload.get("support_tools")
    if not isinstance(supporting, list):
        supporting = []
    supporting_names = _dedupe_names([str(name) for name in supporting if str(name).strip()])
    supporting_names = [name for name in supporting_names if name != target]
    reason_codes = []
    if not target:
        reason_codes.append("selector_target_missing")
    selected = [*supporting_names, *([target] if target else [])]
    return SelectorDecision(
        target_tool=target,
        supporting_tools=supporting_names,
        selected_tools=selected,
        raw=payload,
        reason_codes=reason_codes,
    )


def validate_plan_payload(
    payload: dict[str, Any],
    *,
    selected_target: str,
    hydrated: HydratedCatalog,
    tools_by_name: dict[str, ToolSchema],
) -> PlanValidation:
    """Validate tool names, arguments, bindings, and required-input accounting."""
    raw_steps = payload.get("plan")
    if not isinstance(raw_steps, list):
        raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = []
    final_target = str(payload.get("final_target") or selected_target).strip()
    hydrated_names = set(hydrated.hydrated_names)
    reason_codes: list[str] = []
    plan_tools: list[str] = []
    unknown_tools: list[str] = []
    unknown_arguments: dict[str, list[str]] = {}
    invalid_argument_types: dict[str, list[str]] = {}
    unaccounted_required: dict[str, list[str]] = {}
    invalid_bindings: dict[str, list[str]] = {}
    invalid_binding_paths: dict[str, list[str]] = {}
    invalid_missing_inputs: dict[str, list[str]] = {}

    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            reason_codes.append("plan_step_invalid")
            continue
        tool_name = str(raw_step.get("tool") or raw_step.get("tool_name") or "").strip()
        if not tool_name:
            reason_codes.append("plan_tool_missing")
            continue
        plan_tools.append(tool_name)
        if tool_name not in hydrated_names or tool_name not in tools_by_name:
            unknown_tools.append(tool_name)
            continue

        tool = tools_by_name[tool_name]
        parameters = {parameter.name: parameter for parameter in tool.parameters}
        arguments = raw_step.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        bindings = raw_step.get("bindings")
        if not isinstance(bindings, dict):
            bindings = {}
        missing = raw_step.get("missing_required_inputs")
        if not isinstance(missing, list):
            missing = []
        missing_names = {str(name) for name in missing}
        bad_missing_names = sorted(missing_names - set(parameters))
        if bad_missing_names:
            invalid_missing_inputs[f"{index}:{tool_name}"] = bad_missing_names

        extra_arguments = sorted(set(arguments) - set(parameters))
        if extra_arguments:
            unknown_arguments[f"{index}:{tool_name}"] = extra_arguments
        type_failures = sorted(
            name
            for name, value in arguments.items()
            if name in parameters and not _value_matches_parameter(value, parameters[name])
        )
        if type_failures:
            invalid_argument_types[f"{index}:{tool_name}"] = type_failures

        bad_bindings = []
        for name, binding in bindings.items():
            if name not in parameters or not isinstance(binding, dict):
                bad_bindings.append(str(name))
                continue
            from_tool = str(binding.get("from_tool") or "")
            if from_tool not in plan_tools[:-1]:
                bad_bindings.append(str(name))
                continue
            path = str(binding.get("path") or "")
            source_tool = tools_by_name.get(from_tool)
            if source_tool is None or not _binding_path_is_valid(
                path,
                source_tool,
                parameters[name],
            ):
                invalid_binding_paths.setdefault(f"{index}:{tool_name}", []).append(str(name))
        if bad_bindings:
            invalid_bindings[f"{index}:{tool_name}"] = sorted(bad_bindings)

        covered = set(arguments) | set(bindings) | missing_names
        required = {parameter.name for parameter in tool.parameters if parameter.required}
        missing_coverage = sorted(required - covered)
        if missing_coverage:
            unaccounted_required[f"{index}:{tool_name}"] = missing_coverage

    if unknown_tools:
        reason_codes.append("plan_tool_not_hydrated")
    if unknown_arguments:
        reason_codes.append("plan_unknown_argument")
    if invalid_argument_types:
        reason_codes.append("plan_argument_type_invalid")
    if invalid_bindings:
        reason_codes.append("plan_binding_invalid")
    if invalid_binding_paths:
        reason_codes.append("plan_binding_path_invalid")
    if invalid_missing_inputs:
        reason_codes.append("plan_missing_input_invalid")
    if unaccounted_required:
        reason_codes.append("plan_required_input_unaccounted")
    if not plan_tools:
        reason_codes.append("plan_empty")

    target_consistent = bool(
        selected_target
        and final_target == selected_target
        and plan_tools
        and plan_tools[-1] == selected_target
    )
    if not target_consistent:
        reason_codes.append("plan_final_target_mismatch")

    plan_tool_validity = float(bool(plan_tools) and not unknown_tools)
    argument_schema_validity = float(
        not unknown_arguments
        and not invalid_argument_types
        and not invalid_bindings
        and not invalid_binding_paths
        and not invalid_missing_inputs
    )
    required_input_accounting = float(not unaccounted_required)
    final_target_consistency = float(target_consistent)
    valid = bool(
        hydrated.success
        and plan_tool_validity
        and argument_schema_validity
        and required_input_accounting
        and final_target_consistency
    )
    return PlanValidation(
        final_target=final_target,
        plan_tools=plan_tools,
        plan_tool_validity=plan_tool_validity,
        argument_schema_validity=argument_schema_validity,
        required_input_accounting=required_input_accounting,
        final_target_consistency=final_target_consistency,
        valid=valid,
        reason_codes=list(dict.fromkeys(reason_codes)),
        evidence={
            "unknown_tools": sorted(set(unknown_tools)),
            "unknown_arguments": unknown_arguments,
            "invalid_argument_types": invalid_argument_types,
            "invalid_bindings": invalid_bindings,
            "invalid_binding_paths": invalid_binding_paths,
            "invalid_missing_inputs": invalid_missing_inputs,
            "unaccounted_required": unaccounted_required,
        },
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from a model response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _value_matches_parameter(value: Any, parameter: ToolParameter) -> bool:
    if parameter.enum is not None and value not in parameter.enum:
        return False
    normalized = parameter.type.lower()
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"number", "float", "double"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"array", "list"}:
        return isinstance(value, list)
    if normalized in {"object", "dict"}:
        return isinstance(value, dict)
    if normalized in {"null", "none"}:
        return value is None
    if normalized in {"string", "str"}:
        return isinstance(value, str)
    return True


def _binding_path_is_valid(
    path: str,
    source_tool: ToolSchema,
    target_parameter: ToolParameter,
) -> bool:
    if not path:
        return False
    normalized_path = _normalize_binding_path(path)
    for row in (source_tool.metadata.get("api_contract") or {}).get("produces") or []:
        valid_paths = {
            str(row.get("json_path") or ""),
            *(str(value) for value in row.get("value_path_aliases") or []),
        }
        if normalized_path not in {
            _normalize_binding_path(valid_path) for valid_path in valid_paths
        }:
            continue
        field_name = str(row.get("field_name") or "")
        if not _field_names_compatible(field_name, target_parameter.name):
            continue
        field_type = str(row.get("field_type") or "")
        if field_type and not _field_types_compatible(field_type, target_parameter.type):
            continue
        return True
    return False


def _normalize_binding_path(path: str) -> str:
    return re.sub(r"\[(?:\*|\d+)\]", "[*]", path.strip())


def _compact_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "field_name",
        "json_path",
        "field_type",
        "required",
        "location",
        "kind",
        "semantic_tag",
    )
    value = {key: row[key] for key in keys if row.get(key) not in (None, "")}
    aliases = [str(alias) for alias in row.get("value_path_aliases") or [] if alias]
    if aliases:
        value["value_path_aliases"] = aliases[:4]
    return value


def _field_names_compatible(left: str, right: str) -> bool:
    normalized_left = re.sub(r"[^a-z0-9]", "", left.casefold())
    normalized_right = re.sub(r"[^a-z0-9]", "", right.casefold())
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    return (normalized_left == "id" and normalized_right.endswith("id")) or (
        normalized_right == "id" and normalized_left.endswith("id")
    )


def _field_types_compatible(left: str, right: str) -> bool:
    groups = (
        {"integer", "int", "int32", "int64"},
        {"number", "float", "double"},
        {"boolean", "bool"},
        {"array", "list"},
        {"object", "dict"},
        {"string", "str", "id"},
    )
    normalized_left = left.casefold()
    normalized_right = right.casefold()
    return normalized_left == normalized_right or any(
        normalized_left in group and normalized_right in group for group in groups
    )


def _dedupe_names(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
