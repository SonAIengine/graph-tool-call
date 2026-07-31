"""Run the paired budgeted LLM-catalog versus B6c model-loop baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from time import perf_counter
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
from benchmarks.paper_baselines.token_budget import HuggingFaceTokenCounter, TokenCounter
from graph_tool_call.core.tool import ToolSchema

from .analysis import EFFECTIVENESS_METRICS
from .catalog import (
    B6C_BASELINE,
    HYDRATION_POLICY_REVISION,
    PLAN_VALIDATION_POLICY_REVISION,
    PLANNING_CONTRACT_VIEW_REVISION,
    SELECTION_PROTOCOL_REVISION,
    SelectorDecision,
    build_planning_contract_view,
    hydrate_full_schemas,
    parse_selector_decision,
    validate_paired_case_contract,
    validate_plan_payload,
)
from .client import HTTPModelClient, ModelClient, ModelResponse, redacted_url
from .llm_catalog_baseline import (
    B0L_BASELINE,
    DEFAULT_MAX_HIERARCHY_ROUNDS,
    DEFAULT_SHORTLIST_SIZE,
    LLM_CATALOG_CHUNK_POLICY_REVISION,
    LLM_CATALOG_FINAL_SELECTION_REVISION,
    LLM_CATALOG_INDEX_REVISION,
    LLM_CATALOG_SHORTLIST_REVISION,
    build_llm_catalog_chunks,
    build_llm_catalog_index,
    final_selection_messages,
    local_shortlist_limit,
    parse_shortlist_decision,
    shortlist_messages,
)
from .run import (
    DEFAULT_MAX_PLAN_TOKENS,
    DEFAULT_MAX_SELECTION_TOKENS,
    _evaluate_condition,
    _failure_stage,
    _load_tools_by_source,
    _paired_seed,
    _planning_messages,
    _select_cases,
    _set_recall,
    _sha256_file,
    _validate_baseline_artifact,
    _validate_run_options,
)

DEFAULT_OUTPUT_PATH = "/tmp/graph-tool-call-paper-b0l-vs-b6c.json"
B0L_METHODOLOGY = "paired-budgeted-llm-catalog-vs-b6c-v1"
COMPARISON_BASELINES = (B6C_BASELINE, B0L_BASELINE)
COST_METRICS = (
    "selection_model_call_count",
    "model_call_count",
    "catalog_tokens_scanned",
    "total_input_tokens",
    "total_output_tokens",
    "latency_ms",
)


def run_budgeted_llm_catalog_baseline(
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
    shortlist_size: int = DEFAULT_SHORTLIST_SIZE,
    max_hierarchy_rounds: int = DEFAULT_MAX_HIERARCHY_ROUNDS,
    max_selected_tools: int = 5,
    selector_concurrency: int = 4,
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
    """Compare exhaustive budgeted LLM catalog selection with frozen B6c."""
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
    for name, value in {
        "shortlist_size": shortlist_size,
        "max_hierarchy_rounds": max_hierarchy_rounds,
        "max_selected_tools": max_selected_tools,
        "selector_concurrency": selector_concurrency,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero.")

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
    token_budget_config = baseline_artifact.config.get("token_budget") or {}
    catalog_token_budget = int(token_budget_config.get("limit") or 0)
    if catalog_token_budget <= 0:
        raise ValueError("Baseline artifact must freeze a positive token_budget.limit.")
    _validate_b6c_budget_identity(baseline_artifact.cases, catalog_token_budget)

    resolved_manifest = Path(manifest_path).resolve()
    manifest_sha256 = _sha256_file(resolved_manifest)
    if manifest_sha256 != baseline_artifact.dataset.get("manifest_sha256"):
        raise ValueError("Manifest digest does not match the frozen baseline artifact.")
    manifest = load_corpus_manifest(resolved_manifest)
    selected_cases = _select_cases(baseline_artifact.cases, case_ids=case_ids, limit=limit)
    tools_by_source = _load_tools_by_source(
        manifest,
        resolved_manifest.parent,
        {str(case.get("context", {}).get("source_id") or "") for case in selected_cases},
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

    evaluated: list[dict[str, Any]] = []
    for case in selected_cases:
        source_id = str(case["context"]["source_id"])
        tools_by_name = tools_by_source[source_id]
        pair_contract = validate_paired_case_contract(case)
        for repeat in range(repeats):
            paired_seed = _paired_seed(seed, str(case["case_id"]), repeat)
            condition_order = (
                (B6C_BASELINE, B0L_BASELINE)
                if paired_seed % 2 == 0
                else (B0L_BASELINE, B6C_BASELINE)
            )
            condition_rows: dict[str, dict[str, Any]] = {}
            for invocation_index, baseline in enumerate(condition_order):
                if baseline == B6C_BASELINE:
                    row = _evaluate_condition(
                        case,
                        tools_by_name,
                        baseline=B6C_BASELINE,
                        repeat=repeat,
                        paired_seed=paired_seed,
                        token_counter=token_counter,
                        model_client=model_client,
                        timeout=timeout,
                        max_selection_tokens=max_selection_tokens,
                        max_plan_tokens=max_plan_tokens,
                        pair_contract=pair_contract,
                    )
                    _add_comparison_cost_metrics(row, total_tool_count=len(tools_by_name))
                else:
                    row = _evaluate_b0l_condition(
                        case,
                        tools_by_name,
                        repeat=repeat,
                        paired_seed=paired_seed,
                        token_counter=token_counter,
                        catalog_token_budget=catalog_token_budget,
                        model_client=model_client,
                        timeout=timeout,
                        max_selection_tokens=max_selection_tokens,
                        max_plan_tokens=max_plan_tokens,
                        shortlist_size=shortlist_size,
                        max_hierarchy_rounds=max_hierarchy_rounds,
                        max_selected_tools=max_selected_tools,
                        selector_concurrency=selector_concurrency,
                        pair_contract=pair_contract,
                    )
                row["context"]["condition_invocation_index"] = invocation_index
                row["context"]["condition_order"] = list(condition_order)
                condition_rows[baseline] = row
            evaluated.extend(condition_rows[baseline] for baseline in COMPARISON_BASELINES)

    summary, statistics = _summarize_comparison(
        evaluated,
        bootstrap_resamples=bootstrap_resamples,
        seed=seed,
    )
    replay_command = _replay_command(
        baseline_artifact_path=baseline_artifact_path,
        manifest_path=manifest_path,
        model=model,
        model_revision=model_revision,
        provider=provider,
        llm_url=llm_url,
        output_path=output_path,
        repeats=repeats,
        seed=seed,
        timeout=timeout,
        max_selection_tokens=max_selection_tokens,
        max_plan_tokens=max_plan_tokens,
        shortlist_size=shortlist_size,
        max_hierarchy_rounds=max_hierarchy_rounds,
        max_selected_tools=max_selected_tools,
        selector_concurrency=selector_concurrency,
        bootstrap_resamples=bootstrap_resamples,
        case_ids=case_ids,
        limit=limit,
        allow_held_out=allow_held_out,
        disable_thinking=disable_thinking,
        include_seed=include_seed,
    )
    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-tool-selection-and-plan",
        methodology=B0L_METHODOLOGY,
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
            "baselines": list(COMPARISON_BASELINES),
            "repeats": repeats,
            "timeout_seconds": timeout,
            "catalog_index_revision": LLM_CATALOG_INDEX_REVISION,
            "catalog_chunk_policy_revision": LLM_CATALOG_CHUNK_POLICY_REVISION,
            "catalog_shortlist_revision": LLM_CATALOG_SHORTLIST_REVISION,
            "catalog_final_selection_revision": LLM_CATALOG_FINAL_SELECTION_REVISION,
            "b6c_selection_protocol_revision": SELECTION_PROTOCOL_REVISION,
            "catalog_order": "operation_name_casefold_ascending",
            "catalog_token_budget_per_call": catalog_token_budget,
            "shortlist_size": shortlist_size,
            "max_hierarchy_rounds": max_hierarchy_rounds,
            "max_selected_tools": max_selected_tools,
            "selector_concurrency": selector_concurrency,
            "max_selection_output_tokens": max_selection_tokens,
            "max_plan_output_tokens": max_plan_tokens,
            "hydration_policy_revision": HYDRATION_POLICY_REVISION,
            "plan_validation_policy_revision": PLAN_VALIDATION_POLICY_REVISION,
            "planning_contract_view_revision": PLANNING_CONTRACT_VIEW_REVISION,
            "temperature": 0,
            "paired_seed": True,
            "condition_order": "counterbalanced_by_paired_seed_parity",
            "include_seed": include_seed,
            "disable_thinking": disable_thinking,
            "ground_truth_in_prompt": False,
            "graph_edges_used_by_b0_l": False,
            "retrieval_ranks_used_by_b0_l": False,
            "initial_catalog_coverage_required": True,
            "full_schema_hydration": "after_selection_before_plan",
            "execution_performed": False,
        },
        model={
            "name": model,
            "provider": provider,
            "revision": model_revision,
            "role": "hierarchical_catalog_selector_and_planner",
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
        raise ValueError(f"Generated B0-L artifact is invalid: {codes}")
    return artifact


def _evaluate_b0l_condition(
    source_case: dict[str, Any],
    tools_by_name: dict[str, ToolSchema],
    *,
    repeat: int,
    paired_seed: int,
    token_counter: TokenCounter,
    catalog_token_budget: int,
    model_client: ModelClient,
    timeout: int,
    max_selection_tokens: int,
    max_plan_tokens: int,
    shortlist_size: int,
    max_hierarchy_rounds: int,
    max_selected_tools: int,
    selector_concurrency: int,
    pair_contract: dict[str, Any],
) -> dict[str, Any]:
    query = str(source_case["query"])
    selection = _hierarchical_select(
        query,
        tools_by_name,
        paired_seed=paired_seed,
        token_counter=token_counter,
        catalog_token_budget=catalog_token_budget,
        model_client=model_client,
        timeout=timeout,
        max_selection_tokens=max_selection_tokens,
        shortlist_size=shortlist_size,
        max_hierarchy_rounds=max_hierarchy_rounds,
        max_selected_tools=max_selected_tools,
        selector_concurrency=selector_concurrency,
    )
    decision: SelectorDecision = selection["decision"]
    failure_codes = list(selection["failure_codes"])
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

    hallucinated_names = selection["hallucinated_names"]
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
                json.dumps(
                    build_planning_contract_view(hydrated, tools_by_name),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
            seed=paired_seed,
            timeout=timeout,
            max_tokens=max_plan_tokens,
        )
        if planner_response.error:
            failure_codes.append("planning_model_call_failed")
        plan_payload = _extract_json_object(planner_response.content)
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
    total_latency = selection["wall_latency_ms"] + planner_response.latency_ms
    return {
        "case_id": f"{pair_key}::{B0L_BASELINE}",
        "query": query,
        "context": {
            **dict(source_case.get("context") or {}),
            "original_case_id": source_case["case_id"],
            "baseline": B0L_BASELINE,
            "repeat": repeat,
            "paired_seed": paired_seed,
            "pair_key": pair_key,
            "pair_contract": pair_contract,
        },
        "expected": dict(expected),
        "observed": {
            "selection_catalog": selection["selection_catalog"],
            "hierarchical_selector": selection["trace"],
            "selector": {
                **decision.to_dict(),
                "hallucinated_names": hallucinated_names,
                "response": selection["final_response"].to_dict(),
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
            "selection_catalog_tokens": selection["max_chunk_tokens"],
            "catalog_tokens_scanned": selection["catalog_tokens_scanned"],
            "catalog_tool_coverage_rate": selection["initial_catalog_coverage_rate"],
            "selection_input_tokens": selection["input_tokens"],
            "selection_output_tokens": selection["output_tokens"],
            "planning_input_tokens": planner_response.input_tokens,
            "planning_output_tokens": planner_response.output_tokens,
            "total_input_tokens": selection["input_tokens"] + planner_response.input_tokens,
            "total_output_tokens": selection["output_tokens"] + planner_response.output_tokens,
            "selection_model_call_count": selection["model_call_count"],
            "selection_wall_latency_ms": selection["wall_latency_ms"],
            "selection_model_latency_sum_ms": selection["model_latency_sum_ms"],
            "model_call_count": selection["model_call_count"] + int(planner_called),
            "latency_ms": total_latency,
        },
        "stages": {
            "selection": {
                "status": "failed" if selection["failed"] else "completed",
                "latency_ms": selection["wall_latency_ms"],
                "model_latency_sum_ms": selection["model_latency_sum_ms"],
                "model_call_count": selection["model_call_count"],
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
            "stage": _b0l_failure_stage(failure_codes),
        },
    }


def _hierarchical_select(
    query: str,
    tools_by_name: dict[str, ToolSchema],
    *,
    paired_seed: int,
    token_counter: TokenCounter,
    catalog_token_budget: int,
    model_client: ModelClient,
    timeout: int,
    max_selection_tokens: int,
    shortlist_size: int,
    max_hierarchy_rounds: int,
    max_selected_tools: int,
    selector_concurrency: int,
) -> dict[str, Any]:
    selection_started = perf_counter()
    entries = build_llm_catalog_index(tools_by_name)
    entries_by_name = {str(entry["name"]): entry for entry in entries}
    initial_names = list(entries_by_name)
    current_names = list(initial_names)
    rounds: list[dict[str, Any]] = []
    failure_codes: list[str] = []
    final_response = ModelResponse()
    final_decision = SelectorDecision("", [], [], {}, ["selector_target_missing"])
    final_catalog_names: list[str] = []
    final_catalog_tokens = 0
    catalog_tokens_scanned = 0
    max_chunk_tokens = 0
    input_tokens = 0
    output_tokens = 0
    model_latency_sum_ms = 0.0
    model_call_count = 0
    initial_presented_names: set[str] = set()

    for name, value in {
        "catalog_token_budget": catalog_token_budget,
        "shortlist_size": shortlist_size,
        "max_hierarchy_rounds": max_hierarchy_rounds,
        "max_selected_tools": max_selected_tools,
        "selector_concurrency": selector_concurrency,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero.")

    for round_index in range(max_hierarchy_rounds):
        current_entries = [entries_by_name[name] for name in current_names]
        chunks = build_llm_catalog_chunks(
            current_entries,
            token_counter=token_counter,
            token_budget=catalog_token_budget,
            round_index=round_index,
        )
        if not chunks:
            failure_codes.append("hierarchy_candidate_pool_empty")
            break
        if round_index == 0:
            initial_presented_names.update(name for chunk in chunks for name in chunk.names)
        if len(chunks) == 1:
            chunk = chunks[0]
            final_catalog_names = list(chunk.names)
            final_catalog_tokens = chunk.catalog_tokens
            response = model_client.complete(
                final_selection_messages(
                    query,
                    chunk.serialized,
                    max_selected_tools=max_selected_tools,
                ),
                seed=paired_seed,
                timeout=timeout,
                max_tokens=max_selection_tokens,
            )
            model_call_count += 1
            catalog_tokens_scanned += chunk.catalog_tokens
            max_chunk_tokens = max(max_chunk_tokens, chunk.catalog_tokens)
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            model_latency_sum_ms += response.latency_ms
            final_response = response
            final_decision = parse_selector_decision(response.content)
            failure_codes.extend(final_decision.reason_codes)
            if response.error:
                failure_codes.append("selection_model_call_failed")
            if not _extract_json_object(response.content):
                failure_codes.append("selector_json_invalid")
            if len(final_decision.selected_tools) > max_selected_tools:
                failure_codes.append("selector_selection_limit_exceeded")
                supporting = final_decision.supporting_tools[: max(0, max_selected_tools - 1)]
                final_decision = SelectorDecision(
                    target_tool=final_decision.target_tool,
                    supporting_tools=supporting,
                    selected_tools=[*supporting, final_decision.target_tool],
                    raw=final_decision.raw,
                    reason_codes=final_decision.reason_codes,
                )
            rounds.append(
                {
                    "round_index": round_index,
                    "mode": "final_selection",
                    "input_candidate_count": len(current_names),
                    "chunks": [
                        {
                            **chunk.to_dict(),
                            "response": response.to_dict(),
                            "decision": final_decision.to_dict(),
                        }
                    ],
                    "output_candidate_count": len(final_decision.selected_tools),
                }
            )
            break

        next_names: list[str] = []
        round_chunks = []
        requests = []
        for chunk in chunks:
            local_limit = local_shortlist_limit(
                len(chunk.names),
                shortlist_size=shortlist_size,
            )
            requests.append((chunk, local_limit))
        with ThreadPoolExecutor(
            max_workers=min(selector_concurrency, len(requests)),
            thread_name_prefix="b0l-selector",
        ) as executor:
            futures = [
                executor.submit(
                    model_client.complete,
                    shortlist_messages(query, chunk.serialized, shortlist_size=local_limit),
                    seed=_stage_seed(paired_seed, round_index, chunk.chunk_index),
                    timeout=timeout,
                    max_tokens=max_selection_tokens,
                )
                for chunk, local_limit in requests
            ]
            responses = [future.result() for future in futures]
        for (chunk, local_limit), response in zip(requests, responses, strict=True):
            model_call_count += 1
            catalog_tokens_scanned += chunk.catalog_tokens
            max_chunk_tokens = max(max_chunk_tokens, chunk.catalog_tokens)
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            model_latency_sum_ms += response.latency_ms
            decision = parse_shortlist_decision(response.content, shortlist_size=local_limit)
            if response.error:
                failure_codes.append("shortlist_model_call_failed")
            if not _extract_json_object(response.content):
                failure_codes.append("shortlist_json_invalid")
            failure_codes.extend(decision.reason_codes)
            valid_names = [name for name in decision.candidate_tools if name in chunk.names]
            hallucinated = [name for name in decision.candidate_tools if name not in chunk.names]
            if hallucinated:
                failure_codes.append("shortlist_tool_not_in_chunk")
            next_names.extend(valid_names)
            round_chunks.append(
                {
                    **chunk.to_dict(),
                    "response": response.to_dict(),
                    "decision": decision.to_dict(),
                    "valid_names": valid_names,
                    "hallucinated_names": hallucinated,
                    "local_shortlist_limit": local_limit,
                }
            )
        next_names = list(dict.fromkeys(next_names))
        rounds.append(
            {
                "round_index": round_index,
                "mode": "local_shortlist",
                "input_candidate_count": len(current_names),
                "chunks": round_chunks,
                "output_candidate_count": len(next_names),
            }
        )
        if not next_names:
            failure_codes.append("hierarchy_candidate_pool_empty")
            break
        if len(next_names) >= len(current_names):
            failure_codes.append("hierarchy_no_reduction")
            break
        current_names = next_names
    else:
        failure_codes.append("hierarchy_max_rounds")

    hallucinated_names = sorted(set(final_decision.selected_tools) - set(final_catalog_names))
    if hallucinated_names:
        failure_codes.append("selector_tool_not_in_catalog")
    initial_catalog_coverage_rate = (
        len(initial_presented_names) / len(tools_by_name) if tools_by_name else 0.0
    )
    failure_codes = list(dict.fromkeys(failure_codes))
    wall_latency_ms = (perf_counter() - selection_started) * 1000
    return {
        "decision": final_decision,
        "final_response": final_response,
        "hallucinated_names": hallucinated_names,
        "failure_codes": failure_codes,
        "failed": bool(failure_codes or not final_decision.target_tool),
        "selection_catalog": {
            "baseline": B0L_BASELINE,
            "index_revision": LLM_CATALOG_INDEX_REVISION,
            "chunk_policy_revision": LLM_CATALOG_CHUNK_POLICY_REVISION,
            "shortlist_revision": LLM_CATALOG_SHORTLIST_REVISION,
            "total_tool_count": len(tools_by_name),
            "initial_names_sha256": _sha256_names(initial_names),
            "initial_catalog_coverage_rate": initial_catalog_coverage_rate,
            "final_candidate_names": final_catalog_names,
            "schema_tokens": max_chunk_tokens,
            "token_budget_limit": catalog_token_budget,
            "catalog_tokens_scanned": catalog_tokens_scanned,
            "round_count": len(rounds),
            "initial_chunk_count": len(rounds[0]["chunks"]) if rounds else 0,
            "final_catalog_tokens": final_catalog_tokens,
        },
        "trace": {
            "rounds": rounds,
            "model_call_count": model_call_count,
            "catalog_tokens_scanned": catalog_tokens_scanned,
            "selector_concurrency": selector_concurrency,
            "wall_latency_ms": wall_latency_ms,
            "model_latency_sum_ms": model_latency_sum_ms,
        },
        "initial_catalog_coverage_rate": initial_catalog_coverage_rate,
        "max_chunk_tokens": max_chunk_tokens,
        "catalog_tokens_scanned": catalog_tokens_scanned,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "wall_latency_ms": wall_latency_ms,
        "model_latency_sum_ms": model_latency_sum_ms,
        "model_call_count": model_call_count,
    }


def _summarize_comparison(
    cases: list[dict[str, Any]],
    *,
    bootstrap_resamples: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pairs = _pair_cases(cases)
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
            metric: fmean(float(row["metrics"].get(metric, 0.0)) for row in rows)
            for metric in metric_names
        }
        for baseline, rows in sorted(grouped.items())
    }
    paired_effectiveness = {
        metric: _paired_metric_summary(pairs, metric) for metric in EFFECTIVENESS_METRICS
    }
    paired_cost = {metric: _paired_metric_summary(pairs, metric) for metric in COST_METRICS}
    clustered = {
        metric: _clustered_bootstrap(
            pairs,
            metric,
            bootstrap_resamples=bootstrap_resamples,
            seed=seed,
        )
        for metric in EFFECTIVENESS_METRICS
    }
    repeat_values = sorted({int(case["context"]["repeat"]) for case in cases})
    cluster_values = {str(case["context"]["original_case_id"]) for case in cases}
    expected_pairs = len(repeat_values) * len(cluster_values)
    failures = {
        baseline: dict(
            sorted(
                Counter(
                    reason
                    for row in rows
                    for reason in row.get("failure", {}).get("reason_codes", [])
                ).items()
            )
        )
        for baseline, rows in sorted(grouped.items())
    }
    return (
        {
            "case_count": len(cases),
            "original_case_count": len(cluster_values),
            "baselines": per_baseline,
            "failures": failures,
            "paired_b0_l_minus_b6c": paired_effectiveness,
            "paired_cost_b0_l_minus_b6c": paired_cost,
            "protocol_integrity": {
                "paired_case_count": len(pairs),
                "original_case_cluster_count": len(cluster_values),
                "repeat_count": len(repeat_values),
                "complete_repeat_grid_rate": len(pairs) / expected_pairs if expected_pairs else 0.0,
                "catalog_budget_compliance_rate": fmean(
                    float(
                        row["metrics"]["selection_catalog_tokens"]
                        <= row["observed"]["selection_catalog"]["token_budget_limit"]
                    )
                    for row in cases
                )
                if cases
                else 0.0,
                "b0_l_initial_catalog_coverage_rate": fmean(
                    row["metrics"]["catalog_tool_coverage_rate"]
                    for row in grouped.get(B0L_BASELINE, [])
                )
                if grouped.get(B0L_BASELINE)
                else 0.0,
            },
        },
        {
            "paired_bootstrap": {
                metric: {
                    "confidence": 0.95,
                    "n_resamples": bootstrap_resamples,
                    "mean_delta_ci": list(
                        confidence_interval(
                            [_pair_delta(pair, metric) for pair in pairs],
                            n_bootstrap=bootstrap_resamples,
                            seed=seed,
                        )
                    ),
                }
                for metric in EFFECTIVENESS_METRICS
            },
            "clustered_paired_bootstrap": clustered,
        },
    )


def _pair_cases(cases: list[dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for case in cases:
        context = case.get("context") or {}
        pair_key = str(context.get("pair_key") or "")
        baseline = str(context.get("baseline") or "")
        if not pair_key or baseline not in COMPARISON_BASELINES:
            raise ValueError("Every B0-L comparison row requires a pair_key and known baseline.")
        if baseline in grouped[pair_key]:
            raise ValueError(f"Duplicate B0-L comparison condition for {pair_key}: {baseline}")
        grouped[pair_key][baseline] = case
    expected = set(COMPARISON_BASELINES)
    incomplete = sorted(key for key, pair in grouped.items() if set(pair) != expected)
    if incomplete:
        raise ValueError(f"Incomplete B0-L/B6c pairs: {', '.join(incomplete)}")
    for pair_key, pair in grouped.items():
        identities = {
            (
                str((row.get("context") or {}).get("original_case_id") or ""),
                (row.get("context") or {}).get("repeat"),
            )
            for row in pair.values()
        }
        if len(identities) != 1 or not next(iter(identities))[0]:
            raise ValueError(f"B0-L/B6c pair identity mismatch: {pair_key}")
    return [pair for _, pair in sorted(grouped.items())]


def _paired_metric_summary(
    pairs: list[dict[str, dict[str, Any]]],
    metric: str,
) -> dict[str, Any]:
    before = [_metric(pair[B6C_BASELINE], metric) for pair in pairs]
    after = [_metric(pair[B0L_BASELINE], metric) for pair in pairs]
    deltas = [right - left for left, right in zip(before, after, strict=True)]
    return {
        "mean_before": fmean(before) if before else 0.0,
        "mean_after": fmean(after) if after else 0.0,
        "mean_delta": fmean(deltas) if deltas else 0.0,
        "improvements": sum(delta > 0 for delta in deltas),
        "regressions": sum(delta < 0 for delta in deltas),
        "ties": sum(delta == 0 for delta in deltas),
    }


def _clustered_bootstrap(
    pairs: list[dict[str, dict[str, Any]]],
    metric: str,
    *,
    bootstrap_resamples: int,
    seed: int,
) -> dict[str, Any]:
    by_case: dict[str, list[float]] = defaultdict(list)
    for pair in pairs:
        case_id = str(pair[B6C_BASELINE]["context"]["original_case_id"])
        by_case[case_id].append(_pair_delta(pair, metric))
    cluster_means = [fmean(values) for _, values in sorted(by_case.items())]
    return {
        "confidence": 0.95,
        "n_resamples": bootstrap_resamples,
        "cluster_key": "original_case_id",
        "cluster_count": len(cluster_means),
        "repeated_pair_count": len(pairs),
        "within_cluster_aggregation": "mean_delta",
        "mean_delta": fmean(cluster_means),
        "mean_delta_ci": list(
            confidence_interval(
                cluster_means,
                n_bootstrap=bootstrap_resamples,
                seed=seed,
            )
        ),
    }


def _pair_delta(pair: dict[str, dict[str, Any]], metric: str) -> float:
    return _metric(pair[B0L_BASELINE], metric) - _metric(pair[B6C_BASELINE], metric)


def _metric(case: dict[str, Any], metric: str) -> float:
    value = (case.get("metrics") or {}).get(metric, 0.0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _add_comparison_cost_metrics(case: dict[str, Any], *, total_tool_count: int) -> None:
    catalog = case.get("observed", {}).get("selection_catalog") or {}
    selected = len(catalog.get("selected_names") or [])
    metrics = case["metrics"]
    metrics["selection_model_call_count"] = 1
    metrics["catalog_tokens_scanned"] = metrics["selection_catalog_tokens"]
    metrics["catalog_tool_coverage_rate"] = selected / total_tool_count if total_tool_count else 0.0
    selection_response = case["observed"]["selector"]["response"]
    metrics["selection_wall_latency_ms"] = float(selection_response.get("latency_ms") or 0.0)
    metrics["selection_model_latency_sum_ms"] = float(selection_response.get("latency_ms") or 0.0)


def _validate_b6c_budget_identity(cases: list[dict[str, Any]], expected_limit: int) -> None:
    limits = {
        int(
            ((case.get("token_budget_observed") or {}).get(B6C_BASELINE) or {}).get(
                "token_budget_limit"
            )
            or 0
        )
        for case in cases
    }
    if limits != {expected_limit}:
        raise ValueError("B0-L and B6c must use the same frozen per-call catalog token budget.")


def _stage_seed(seed: int, round_index: int, chunk_index: int) -> int:
    digest = hashlib.sha256(f"{seed}:shortlist:{round_index}:{chunk_index}".encode()).hexdigest()
    return int(digest[:8], 16)


def _b0l_failure_stage(reason_codes: list[str]) -> str:
    if any(code.startswith(("shortlist_", "hierarchy_")) for code in reason_codes):
        return "selection"
    return _failure_stage(reason_codes)


def _sha256_names(names: list[str]) -> str:
    value = json.dumps(names, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _extract_json_object(text: str) -> dict[str, Any]:
    from .catalog import extract_json_object

    return extract_json_object(text)


def _replay_command(**options: Any) -> list[str]:
    command = [
        "python",
        "-m",
        "benchmarks.paper_model_loop.llm_catalog_run",
        "--baseline-artifact",
        str(options["baseline_artifact_path"]),
        "--manifest",
        str(options["manifest_path"]),
        "--model",
        options["model"],
        "--model-revision",
        options["model_revision"],
        "--provider",
        options["provider"],
        "--llm-url",
        redacted_url(options["llm_url"]),
        "--repeats",
        str(options["repeats"]),
        "--seed",
        str(options["seed"]),
        "--timeout",
        str(options["timeout"]),
        "--max-selection-tokens",
        str(options["max_selection_tokens"]),
        "--max-plan-tokens",
        str(options["max_plan_tokens"]),
        "--shortlist-size",
        str(options["shortlist_size"]),
        "--max-hierarchy-rounds",
        str(options["max_hierarchy_rounds"]),
        "--max-selected-tools",
        str(options["max_selected_tools"]),
        "--selector-concurrency",
        str(options["selector_concurrency"]),
        "--bootstrap-resamples",
        str(options["bootstrap_resamples"]),
        "--out",
        str(options["output_path"]),
    ]
    for case_id in options["case_ids"]:
        command.extend(["--case-id", case_id])
    if options["limit"] is not None:
        command.extend(["--limit", str(options["limit"])])
    if options["allow_held_out"]:
        command.append("--allow-held-out")
    if not options["disable_thinking"]:
        command.append("--no-disable-thinking")
    if not options["include_seed"]:
        command.append("--no-include-seed")
    return command


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-artifact", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--provider", choices=("openai-compatible", "ollama"), required=True)
    parser.add_argument("--llm-url", required=True)
    parser.add_argument("--out", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-selection-tokens", type=int, default=DEFAULT_MAX_SELECTION_TOKENS)
    parser.add_argument("--max-plan-tokens", type=int, default=DEFAULT_MAX_PLAN_TOKENS)
    parser.add_argument("--shortlist-size", type=int, default=DEFAULT_SHORTLIST_SIZE)
    parser.add_argument(
        "--max-hierarchy-rounds",
        type=int,
        default=DEFAULT_MAX_HIERARCHY_ROUNDS,
    )
    parser.add_argument("--max-selected-tools", type=int, default=5)
    parser.add_argument("--selector-concurrency", type=int, default=4)
    parser.add_argument("--bootstrap-resamples", type=int, default=1000)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--disable-thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-seed", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = run_budgeted_llm_catalog_baseline(
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
        shortlist_size=args.shortlist_size,
        max_hierarchy_rounds=args.max_hierarchy_rounds,
        max_selected_tools=args.max_selected_tools,
        selector_concurrency=args.selector_concurrency,
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
    print(json.dumps(artifact.summary["paired_b0_l_minus_b6c"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
