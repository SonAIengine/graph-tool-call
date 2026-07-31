"""Run a paired B6b/B6c two-pass model-in-the-loop experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.corpus.manifest import DEFAULT_MANIFEST_PATH, load_corpus_manifest
from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    finalize_artifact,
    load_artifact,
    validate_artifact,
    write_artifact,
)
from benchmarks.metrics import confidence_interval
from benchmarks.paper_baselines.token_budget import (
    HuggingFaceTokenCounter,
    TokenCounter,
    serialize_model_facing_payloads,
)
from graph_tool_call import ingest_source
from graph_tool_call.core.tool import ToolSchema

from .catalog import (
    B6B_BASELINE,
    B6C_BASELINE,
    HYDRATION_POLICY_REVISION,
    MODEL_LOOP_BASELINES,
    PLAN_VALIDATION_POLICY_REVISION,
    PLANNING_CONTRACT_VIEW_REVISION,
    SELECTION_PROTOCOL_REVISION,
    build_planning_contract_view,
    build_selection_catalog,
    extract_json_object,
    hydrate_full_schemas,
    parse_selector_decision,
    validate_paired_case_contract,
    validate_plan_payload,
)
from .client import HTTPModelClient, ModelClient, ModelResponse, redacted_url

DEFAULT_OUTPUT_PATH = "/tmp/graph-tool-call-paper-b6c-model-loop.json"
DEFAULT_MAX_SELECTION_TOKENS = 384
DEFAULT_MAX_PLAN_TOKENS = 1024
MODEL_LOOP_METHODOLOGY = "paired-b6b-b6c-two-pass-model-loop-v1"
EFFECTIVENESS_METRICS = (
    "selector_target_accuracy",
    "selector_producer_recall",
    "selector_required_tool_recall",
    "all_required_selected",
    "hydration_success",
    "plan_tool_validity",
    "argument_schema_validity",
    "required_input_accounting",
    "end_to_end_valid",
)


def run_paired_model_loop(
    baseline_artifact_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    model: str,
    model_revision: str,
    provider: str,
    llm_url: str,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    repeats: int = 1,
    seed: int = 17,
    timeout: int = 180,
    max_selection_tokens: int = DEFAULT_MAX_SELECTION_TOKENS,
    max_plan_tokens: int = DEFAULT_MAX_PLAN_TOKENS,
    bootstrap_resamples: int = 1000,
    case_ids: tuple[str, ...] = (),
    limit: int | None = None,
    allow_held_out: bool = False,
    disable_thinking: bool = True,
    include_seed: bool = True,
    created_at: str | None = None,
    model_client: ModelClient | None = None,
    token_counter: TokenCounter | None = None,
) -> ExperimentArtifact:
    """Evaluate B6b and B6c with the same frozen model and paired seeds."""
    _validate_run_options(
        model=model,
        model_revision=model_revision,
        provider=provider,
        repeats=repeats,
        timeout=timeout,
        max_selection_tokens=max_selection_tokens,
        max_plan_tokens=max_plan_tokens,
        bootstrap_resamples=bootstrap_resamples,
        limit=limit,
    )
    baseline_path = Path(baseline_artifact_path).resolve()
    baseline_artifact = load_artifact(baseline_path)
    baseline_validation = validate_artifact(
        baseline_artifact,
        artifact_path=str(baseline_path),
    )
    if not baseline_validation.valid:
        codes = ", ".join(issue.code for issue in baseline_validation.issues)
        raise ValueError(f"Baseline artifact is invalid: {codes}")
    _validate_baseline_artifact(baseline_artifact, allow_held_out=allow_held_out)

    resolved_manifest = Path(manifest_path).resolve()
    manifest_sha256 = _sha256_file(resolved_manifest)
    if manifest_sha256 != baseline_artifact.dataset.get("manifest_sha256"):
        raise ValueError("Manifest digest does not match the frozen baseline artifact.")
    manifest = load_corpus_manifest(resolved_manifest)
    tools_by_source = _load_tools_by_source(
        manifest,
        resolved_manifest.parent,
        {str(case.get("context", {}).get("source_id") or "") for case in baseline_artifact.cases},
    )

    tokenizer_metadata = dict(baseline_artifact.tokenizer)
    if token_counter is None:
        token_counter = HuggingFaceTokenCounter(
            name=str(tokenizer_metadata["name"]),
            revision=str(tokenizer_metadata["revision"]),
        )
        token_counter.warmup()
    if model_client is None:
        model_client = HTTPModelClient(
            model=model,
            url=llm_url,
            provider=provider,
            disable_thinking=disable_thinking,
            include_seed=include_seed,
        )

    selected_cases = _select_cases(
        baseline_artifact.cases,
        case_ids=case_ids,
        limit=limit,
    )
    evaluated: list[dict[str, Any]] = []
    for case in selected_cases:
        source_id = str(case["context"]["source_id"])
        tools_by_name = tools_by_source.get(source_id)
        if tools_by_name is None:
            raise ValueError(f"Missing source tool catalog for {source_id}.")
        pair_contract = validate_paired_case_contract(case)
        for repeat in range(repeats):
            paired_seed = _paired_seed(seed, str(case["case_id"]), repeat)
            for baseline in MODEL_LOOP_BASELINES:
                evaluated.append(
                    _evaluate_condition(
                        case,
                        tools_by_name,
                        baseline=baseline,
                        repeat=repeat,
                        paired_seed=paired_seed,
                        token_counter=token_counter,
                        model_client=model_client,
                        timeout=timeout,
                        max_selection_tokens=max_selection_tokens,
                        max_plan_tokens=max_plan_tokens,
                        pair_contract=pair_contract,
                    )
                )

    summary, statistics = _summarize(
        evaluated,
        bootstrap_resamples=bootstrap_resamples,
        seed=seed,
    )
    replay_command = [
        "python",
        "-m",
        "benchmarks.paper_model_loop.run",
        "--baseline-artifact",
        str(baseline_artifact_path),
        "--manifest",
        str(manifest_path),
        "--model",
        model,
        "--model-revision",
        model_revision,
        "--provider",
        provider,
        "--llm-url",
        redacted_url(llm_url),
        "--repeats",
        str(repeats),
        "--seed",
        str(seed),
        "--timeout",
        str(timeout),
        "--max-selection-tokens",
        str(max_selection_tokens),
        "--max-plan-tokens",
        str(max_plan_tokens),
        "--bootstrap-resamples",
        str(bootstrap_resamples),
        "--out",
        str(output_path),
    ]
    for case_id in case_ids:
        replay_command.extend(["--case-id", case_id])
    if limit is not None:
        replay_command.extend(["--limit", str(limit)])
    if allow_held_out:
        replay_command.append("--allow-held-out")
    if not disable_thinking:
        replay_command.append("--no-disable-thinking")
    if not include_seed:
        replay_command.append("--no-include-seed")

    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-tool-selection-and-plan",
        methodology=MODEL_LOOP_METHODOLOGY,
        run_kind="model",
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        seed=seed,
        dataset={
            **dict(baseline_artifact.dataset),
            "baseline_artifact_id": baseline_artifact.artifact_id,
            "baseline_run_id": baseline_artifact.run_id,
            "selected_case_count": len(selected_cases),
        },
        config={
            "baselines": list(MODEL_LOOP_BASELINES),
            "repeats": repeats,
            "timeout_seconds": timeout,
            "selection_protocol_revision": SELECTION_PROTOCOL_REVISION,
            "hydration_policy_revision": HYDRATION_POLICY_REVISION,
            "plan_validation_policy_revision": PLAN_VALIDATION_POLICY_REVISION,
            "planning_contract_view_revision": PLANNING_CONTRACT_VIEW_REVISION,
            "max_selection_output_tokens": max_selection_tokens,
            "max_plan_output_tokens": max_plan_tokens,
            "temperature": 0,
            "paired_seed": True,
            "include_seed": include_seed,
            "disable_thinking": disable_thinking,
            "selection_catalog_budget": dict(baseline_artifact.config.get("token_budget") or {}),
            "ground_truth_in_prompt": False,
            "full_schema_hydration": "after_selection_before_plan",
            "execution_performed": False,
        },
        model={
            "name": model,
            "provider": provider,
            "revision": model_revision,
            "role": "catalog_selector_and_planner",
            "endpoint": redacted_url(llm_url),
        },
        tokenizer=tokenizer_metadata,
        replay={"command": replay_command, "working_directory": "."},
        summary=summary,
        statistics=statistics,
        cases=evaluated,
        source={
            "type": "paper_baseline_experiment_artifact",
            "sha256": _sha256_file(baseline_path),
            "artifact_id": baseline_artifact.artifact_id,
        },
    )
    finalize_artifact(artifact)
    validation = validate_artifact(artifact)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Generated model-loop artifact is invalid: {codes}")
    return artifact


def _evaluate_condition(
    source_case: dict[str, Any],
    tools_by_name: dict[str, ToolSchema],
    *,
    baseline: str,
    repeat: int,
    paired_seed: int,
    token_counter: TokenCounter,
    model_client: ModelClient,
    timeout: int,
    max_selection_tokens: int,
    max_plan_tokens: int,
    pair_contract: dict[str, Any],
) -> dict[str, Any]:
    catalog = build_selection_catalog(
        source_case,
        tools_by_name,
        baseline=baseline,
        token_counter=token_counter,
    )
    query = str(source_case["query"])
    selection_response = model_client.complete(
        _selection_messages(query, catalog.serialized),
        seed=paired_seed,
        timeout=timeout,
        max_tokens=max_selection_tokens,
    )
    failure_codes: list[str] = []
    selection_payload = extract_json_object(selection_response.content)
    if selection_response.error:
        failure_codes.append("selection_model_call_failed")
    if not selection_payload:
        failure_codes.append("selector_json_invalid")
    decision = parse_selector_decision(selection_response.content)
    failure_codes.extend(decision.reason_codes)
    catalog_names = set(catalog.selected_names)
    hallucinated_names = sorted(set(decision.selected_tools) - catalog_names)
    if hallucinated_names:
        failure_codes.append("selector_tool_not_in_catalog")

    expected = source_case.get("expected") or {}
    expected_targets = set(expected.get("expected_targets") or [])
    alternatives = set(expected.get("acceptable_alternatives") or [])
    required_producers = set(expected.get("required_producers") or [])
    target_options = expected_targets | alternatives
    required_tools = expected_targets | required_producers
    selected_set = set(decision.selected_tools)
    selector_target_accuracy = float(decision.target_tool in target_options)
    selector_producer_recall = _set_recall(selected_set, required_producers)
    selector_required_tool_recall = _set_recall(selected_set, required_tools)
    all_required_selected = float(required_tools.issubset(selected_set))

    hydrated = hydrate_full_schemas(
        decision.selected_tools if not hallucinated_names else [],
        tools_by_name,
    )
    if decision.selected_tools and not hydrated.success:
        failure_codes.append("full_schema_hydration_failed")
    if not decision.selected_tools:
        failure_codes.append("selection_empty")

    planner_response = ModelResponse()
    planner_called = False
    plan_payload: dict[str, Any] = {}
    plan_validation = validate_plan_payload(
        {},
        selected_target=decision.target_tool,
        hydrated=hydrated,
        tools_by_name=tools_by_name,
    )
    if hydrated.success and decision.target_tool and not hallucinated_names:
        planner_called = True
        planner_response = model_client.complete(
            _planning_messages(
                query,
                decision.to_dict(),
                serialize_model_facing_payloads(
                    build_planning_contract_view(hydrated, tools_by_name)
                ),
            ),
            seed=paired_seed,
            timeout=timeout,
            max_tokens=max_plan_tokens,
        )
        if planner_response.error:
            failure_codes.append("planning_model_call_failed")
        plan_payload = extract_json_object(planner_response.content)
        if not plan_payload:
            failure_codes.append("plan_json_invalid")
        plan_validation = validate_plan_payload(
            plan_payload,
            selected_target=decision.target_tool,
            hydrated=hydrated,
            tools_by_name=tools_by_name,
        )
        failure_codes.extend(plan_validation.reason_codes)

    end_to_end_valid = float(
        selector_target_accuracy
        and all_required_selected
        and hydrated.success
        and plan_validation.valid
    )
    failure_codes = list(dict.fromkeys(failure_codes))
    pair_key = f"{source_case['case_id']}::repeat-{repeat}"
    model_call_count = 1 + int(planner_called)
    total_latency = selection_response.latency_ms + planner_response.latency_ms
    return {
        "case_id": f"{pair_key}::{baseline}",
        "query": query,
        "context": {
            **dict(source_case.get("context") or {}),
            "original_case_id": source_case["case_id"],
            "baseline": baseline,
            "repeat": repeat,
            "paired_seed": paired_seed,
            "pair_key": pair_key,
            "pair_contract": pair_contract,
        },
        "expected": dict(expected),
        "observed": {
            "selection_catalog": catalog.to_dict(),
            "selector": {
                **decision.to_dict(),
                "hallucinated_names": hallucinated_names,
                "response": selection_response.to_dict(),
            },
            "hydration": hydrated.to_dict(),
            "plan": {
                "payload": plan_payload,
                "validation": plan_validation.to_dict(),
                "response": planner_response.to_dict(),
            },
        },
        "metrics": {
            "selector_target_accuracy": selector_target_accuracy,
            "selector_producer_recall": selector_producer_recall,
            "selector_required_tool_recall": selector_required_tool_recall,
            "all_required_selected": all_required_selected,
            "selector_hallucination_free": float(not hallucinated_names),
            "hydration_success": float(hydrated.success and bool(decision.selected_tools)),
            "plan_tool_validity": plan_validation.plan_tool_validity,
            "argument_schema_validity": plan_validation.argument_schema_validity,
            "required_input_accounting": plan_validation.required_input_accounting,
            "final_target_consistency": plan_validation.final_target_consistency,
            "end_to_end_valid": end_to_end_valid,
            "selection_catalog_tokens": catalog.schema_tokens,
            "selection_input_tokens": selection_response.input_tokens,
            "selection_output_tokens": selection_response.output_tokens,
            "planning_input_tokens": planner_response.input_tokens,
            "planning_output_tokens": planner_response.output_tokens,
            "total_input_tokens": (selection_response.input_tokens + planner_response.input_tokens),
            "total_output_tokens": (
                selection_response.output_tokens + planner_response.output_tokens
            ),
            "model_call_count": model_call_count,
            "latency_ms": total_latency,
        },
        "stages": {
            "selection": {
                "status": "failed" if selection_response.error else "completed",
                "latency_ms": selection_response.latency_ms,
            },
            "hydration": {
                "status": "completed" if hydrated.success else "failed",
                "hydrated_count": len(hydrated.hydrated_names),
            },
            "planning": {
                "status": (
                    "completed"
                    if planner_response.content and not planner_response.error
                    else "not_run"
                    if not planner_called
                    else "failed"
                ),
                "latency_ms": planner_response.latency_ms,
            },
        },
        "failure": {
            "reason_codes": failure_codes,
            "stage": _failure_stage(failure_codes),
        },
    }


def _selection_messages(query: str, serialized_catalog: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Select API tools only from the supplied catalog. Return one JSON object "
                'with schema {"target_tool": string, "supporting_tools": [string]}. '
                "The target is the final operation satisfying the request. Supporting tools "
                "must run before the target and provide data needed by it. Use exact catalog "
                "names, do not invent tools, and return no prose."
            ),
        },
        {
            "role": "user",
            "content": f"Request:\n{query}\n\nFrozen tool catalog:\n{serialized_catalog}",
        },
    ]


def _planning_messages(
    query: str,
    selector_decision: dict[str, Any],
    hydrated_schemas: str,
) -> list[dict[str, str]]:
    output_schema = {
        "final_target": "exact selected target name",
        "plan": [
            {
                "tool": "exact hydrated tool name",
                "arguments": {"parameter": "literal value known from the request"},
                "bindings": {
                    "parameter": {
                        "from_tool": "earlier tool name",
                        "path": "result field path",
                    }
                },
                "missing_required_inputs": ["required parameter with no known value or binding"],
            }
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "Create an ordered API plan using only the hydrated complete schemas. "
                "Every required parameter must be accounted for by a literal argument, a "
                "binding from an earlier step, or missing_required_inputs. Never fabricate "
                "values. Put supporting tools before the selected target, make the selected "
                "target the final step, and return one JSON object with no prose."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Request:\n{query}\n\nSelection:\n"
                f"{json.dumps(selector_decision, ensure_ascii=False, sort_keys=True)}\n\n"
                f"Hydrated complete schemas:\n{hydrated_schemas}\n\n"
                f"Required output shape:\n"
                f"{json.dumps(output_schema, ensure_ascii=False, sort_keys=True)}"
            ),
        },
    ]


def _summarize(
    cases: list[dict[str, Any]],
    *,
    bootstrap_resamples: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[str(case["context"]["baseline"])].append(case)
    metric_names = sorted(
        {
            metric
            for case in cases
            for metric, value in case.get("metrics", {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    per_baseline = {
        baseline: {
            metric: fmean(float(case["metrics"][metric]) for case in rows)
            for metric in metric_names
        }
        for baseline, rows in sorted(grouped.items())
    }
    failures = {
        baseline: dict(
            sorted(
                Counter(
                    reason
                    for case in rows
                    for reason in case.get("failure", {}).get("reason_codes", [])
                ).items()
            )
        )
        for baseline, rows in sorted(grouped.items())
    }
    paired_rows = _paired_rows(cases)
    paired_summary = {
        metric: _paired_metric_summary(paired_rows, metric) for metric in EFFECTIVENESS_METRICS
    }
    protocol = {
        "paired_case_count": len(paired_rows),
        "ranking_identity_rate": fmean(
            float(case["context"]["pair_contract"]["ranking_identical"]) for case in cases
        )
        if cases
        else 0.0,
        "catalog_budget_compliance_rate": fmean(
            float(
                case["metrics"]["selection_catalog_tokens"]
                <= case["observed"]["selection_catalog"]["token_budget_limit"]
            )
            for case in cases
        )
        if cases
        else 0.0,
    }
    statistics = {
        "paired_bootstrap": {
            metric: {
                "confidence": 0.95,
                "n_resamples": bootstrap_resamples,
                "mean_delta_ci": list(
                    confidence_interval(
                        [
                            pair[B6C_BASELINE]["metrics"][metric]
                            - pair[B6B_BASELINE]["metrics"][metric]
                            for pair in paired_rows
                        ],
                        n_bootstrap=bootstrap_resamples,
                        seed=seed,
                    )
                ),
            }
            for metric in EFFECTIVENESS_METRICS
        }
    }
    return (
        {
            "case_count": len(cases),
            "original_case_count": len({case["context"]["original_case_id"] for case in cases}),
            "baselines": per_baseline,
            "failures": failures,
            "paired_b6c_minus_b6b": paired_summary,
            "protocol_integrity": protocol,
        },
        statistics,
    )


def _paired_rows(cases: list[dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for case in cases:
        grouped[str(case["context"]["pair_key"])][str(case["context"]["baseline"])] = case
    return [pair for _, pair in sorted(grouped.items()) if set(pair) == set(MODEL_LOOP_BASELINES)]


def _paired_metric_summary(
    paired_rows: list[dict[str, dict[str, Any]]],
    metric: str,
) -> dict[str, Any]:
    deltas = [
        float(pair[B6C_BASELINE]["metrics"][metric]) - float(pair[B6B_BASELINE]["metrics"][metric])
        for pair in paired_rows
    ]
    return {
        "mean_before": fmean(float(pair[B6B_BASELINE]["metrics"][metric]) for pair in paired_rows)
        if paired_rows
        else 0.0,
        "mean_after": fmean(float(pair[B6C_BASELINE]["metrics"][metric]) for pair in paired_rows)
        if paired_rows
        else 0.0,
        "mean_delta": fmean(deltas) if deltas else 0.0,
        "improvements": sum(delta > 0 for delta in deltas),
        "regressions": sum(delta < 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
    }


def _load_tools_by_source(
    manifest: dict[str, Any],
    manifest_root: Path,
    source_ids: set[str],
) -> dict[str, dict[str, ToolSchema]]:
    catalogs: dict[str, dict[str, ToolSchema]] = {}
    for source in manifest.get("sources") or []:
        source_id = str(source.get("id") or "")
        if source_id not in source_ids:
            continue
        snapshot = _read_json(manifest_root / str(source["snapshot_path"]))
        ingested = ingest_source(
            snapshot,
            format_hint=str(source["adapter"]),
            **(source.get("ingest_options") or {}),
        )
        unique: dict[str, ToolSchema] = {}
        for tool in ingested.tools:
            unique.setdefault(tool.name, tool)
        catalogs[source_id] = unique
    missing_sources = sorted(source_ids - set(catalogs))
    if missing_sources:
        raise ValueError(f"Manifest is missing source catalogs: {', '.join(missing_sources)}")
    return catalogs


def _select_cases(
    cases: list[dict[str, Any]],
    *,
    case_ids: tuple[str, ...],
    limit: int | None,
) -> list[dict[str, Any]]:
    requested = set(case_ids)
    selected = [case for case in cases if not requested or str(case.get("case_id")) in requested]
    if requested:
        found = {str(case.get("case_id")) for case in selected}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(f"Unknown case IDs: {', '.join(missing)}")
    if limit is not None:
        selected = selected[:limit]
    return selected


def _validate_baseline_artifact(
    artifact: ExperimentArtifact,
    *,
    allow_held_out: bool,
) -> None:
    if artifact.run_kind != "deterministic":
        raise ValueError("Baseline artifact must be a deterministic paper run.")
    if artifact.benchmark != "public-heterogeneous-tool-retrieval":
        raise ValueError("Baseline artifact has the wrong benchmark identity.")
    if artifact.dataset.get("held_out_accessed") and not allow_held_out:
        raise ValueError("Held-out baseline access requires --allow-held-out.")
    configured = set((artifact.config.get("baselines") or {}).keys())
    missing = set(MODEL_LOOP_BASELINES) - configured
    if missing:
        raise ValueError(f"Baseline artifact is missing B6b/B6c: {', '.join(sorted(missing))}")


def _validate_run_options(
    *,
    model: str,
    model_revision: str,
    provider: str,
    repeats: int,
    timeout: int,
    max_selection_tokens: int,
    max_plan_tokens: int,
    bootstrap_resamples: int,
    limit: int | None,
) -> None:
    if not model.strip() or not model_revision.strip():
        raise ValueError("model and model_revision must be non-empty.")
    if provider not in {"openai-compatible", "ollama", "injected"}:
        raise ValueError("provider must be openai-compatible, ollama, or injected.")
    for name, value in {
        "repeats": repeats,
        "timeout": timeout,
        "max_selection_tokens": max_selection_tokens,
        "max_plan_tokens": max_plan_tokens,
        "bootstrap_resamples": bootstrap_resamples,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero.")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than zero.")


def _set_recall(selected: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(selected & expected) / len(expected)


def _paired_seed(seed: int, case_id: str, repeat: int) -> int:
    digest = hashlib.sha256(f"{seed}:{case_id}:{repeat}".encode()).hexdigest()
    return int(digest[:8], 16)


def _failure_stage(reason_codes: list[str]) -> str:
    if any(code.startswith("selection_") or code.startswith("selector_") for code in reason_codes):
        return "selection"
    if any(code.startswith("full_schema_") for code in reason_codes):
        return "hydration"
    if any(code.startswith("plan") or code.startswith("planning_") for code in reason_codes):
        return "planning"
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-artifact", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument(
        "--provider",
        choices=("openai-compatible", "ollama"),
        required=True,
    )
    parser.add_argument("--llm-url", required=True)
    parser.add_argument("--out", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-selection-tokens", type=int, default=DEFAULT_MAX_SELECTION_TOKENS)
    parser.add_argument("--max-plan-tokens", type=int, default=DEFAULT_MAX_PLAN_TOKENS)
    parser.add_argument("--bootstrap-resamples", type=int, default=1000)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument(
        "--disable-thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--include-seed",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = run_paired_model_loop(
        args.baseline_artifact,
        manifest_path=args.manifest,
        model=args.model,
        model_revision=args.model_revision,
        provider=args.provider,
        llm_url=args.llm_url,
        output_path=args.out,
        repeats=args.repeats,
        seed=args.seed,
        timeout=args.timeout,
        max_selection_tokens=args.max_selection_tokens,
        max_plan_tokens=args.max_plan_tokens,
        bootstrap_resamples=args.bootstrap_resamples,
        case_ids=tuple(args.case_id),
        limit=args.limit,
        allow_held_out=args.allow_held_out,
        disable_thinking=args.disable_thinking,
        include_seed=args.include_seed,
    )
    output = write_artifact(args.out, artifact)
    print(f"artifact={output}")
    print(f"artifact_id={artifact.artifact_id}")
    print(f"run_id={artifact.run_id}")
    print(json.dumps(artifact.summary["paired_b6c_minus_b6b"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
