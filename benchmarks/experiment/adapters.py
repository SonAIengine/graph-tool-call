"""Backward-compatible adapters from existing benchmark reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    collect_runtime_provenance,
    finalize_artifact,
)

ALLOWED_SOURCE_TYPES = frozenset(
    {
        "bfcl_model",
        "bfcl_tool_selection",
        "execution",
        "pipeline",
        "reporter",
        "xgen_api_scale",
        "xgen_tool_graph",
    }
)


def adapt_legacy_report(
    report: Any,
    *,
    source_type: str,
    benchmark: str | None = None,
    methodology: str | None = None,
    run_kind: str | None = None,
    seed: int = 0,
    dataset: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
    tokenizer: dict[str, Any] | None = None,
    replay_command: list[str] | None = None,
    repository_root: str | Path | None = None,
) -> ExperimentArtifact:
    """Adapt an existing report without changing its original serializer."""
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"Unsupported experiment source_type: {source_type}")
    payload = _to_dict(report)
    inferred_kind = run_kind or _run_kind(source_type, payload)
    inferred_model = model or _model_metadata(payload, inferred_kind)
    cases = _extract_cases(payload, source_type)
    source_digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    dataset_metadata = dict(
        dataset
        or {
            "id": str(payload.get("benchmark") or source_type),
            "split": "unspecified",
        }
    )
    dataset_metadata.setdefault("source_sha256", source_digest)
    frozen_replay_command = replay_command or _default_replay_command(source_type)
    artifact = ExperimentArtifact(
        benchmark=benchmark or str(payload.get("benchmark") or source_type),
        methodology=methodology or str(payload.get("methodology") or source_type),
        run_kind=inferred_kind,
        created_at=str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        status=_status(payload),
        seed=seed,
        dataset=dataset_metadata,
        config=_merge_config(payload, config),
        provenance=collect_runtime_provenance(repository_root),
        model=inferred_model,
        tokenizer=tokenizer or {},
        replay={"command": frozen_replay_command, "working_directory": "."},
        summary=_summary(payload, source_type),
        statistics=_statistics(payload, source_type),
        cases=cases,
        source={
            "type": source_type,
            "sha256": source_digest,
            "adapter_non_destructive": True,
            "legacy_report_embedded": False,
        },
    )
    return finalize_artifact(artifact, repository_root=repository_root)


def _extract_cases(payload: dict[str, Any], source_type: str) -> list[dict[str, Any]]:
    if source_type in {"bfcl_model", "bfcl_tool_selection"}:
        rows = [
            (case, {"category": category.get("category")})
            for category in payload.get("categories") or []
            if isinstance(category, dict)
            for case in category.get("cases") or []
            if isinstance(case, dict)
        ]
    elif source_type == "xgen_tool_graph":
        rows = [
            (case, {"pipeline": pipeline.get("name")})
            for pipeline in payload.get("pipelines") or []
            if isinstance(pipeline, dict)
            for case in pipeline.get("cases") or []
            if isinstance(case, dict)
        ]
    elif source_type in {"pipeline", "reporter"}:
        rows = [
            (case, {"dataset": dataset.get("name")})
            for dataset in payload.get("datasets") or []
            if isinstance(dataset, dict)
            for case in (dataset.get("queries") or dataset.get("cases") or [])
            if isinstance(case, dict)
        ]
    else:
        rows = [(case, {}) for case in payload.get("cases") or [] if isinstance(case, dict)]

    cases: list[dict[str, Any]] = []
    generated_ids: dict[str, int] = {}
    for index, (row, context) in enumerate(rows):
        base_case_id = str(row.get("case_id") or _case_fingerprint(row) or f"case-{index + 1}")
        occurrence = generated_ids.get(base_case_id, 0) + 1
        generated_ids[base_case_id] = occurrence
        case_id = base_case_id if occurrence == 1 else f"{base_case_id}::{occurrence}"
        cases.append(_normalize_case(case_id, row, context))
    return cases


def _normalize_case(
    case_id: str,
    row: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        key: row[key]
        for key in (
            "expected_any",
            "expected_calls",
            "expected_plan",
            "expected_producers",
            "expected_target",
            "expected_tools",
        )
        if key in row
    }
    observed = {
        key: row[key]
        for key in (
            "baseline_tool",
            "candidates",
            "plan_candidates",
            "plan_steps",
            "predicted_calls",
            "producer_candidates",
            "results",
            "retrieve_tool",
            "retrieved",
            "retrieved_tools",
            "score_breakdown",
            "selected_target",
            "target_selector_candidates",
            "tools_presented",
        )
        if key in row
    }
    metrics = {key: value for key, value in row.items() if isinstance(value, int | float | bool)}
    failure = {
        key: row[key]
        for key in ("error", "failure_category", "failure_reason", "failure_tags", "issues")
        if row.get(key)
    }
    stages = {
        key: row[key]
        for key in ("runner_events", "synthesis_diagnostics", "target_selector")
        if row.get(key) is not None
    }
    return {
        "case_id": case_id,
        "query": str(row.get("query") or ""),
        "context": {
            **context,
            **{
                key: row[key]
                for key in ("category", "difficulty", "tool_source")
                if row.get(key) not in (None, "")
            },
        },
        "expected": expected,
        "observed": observed,
        "metrics": metrics,
        "stages": stages,
        "failure": failure,
    }


def _merge_config(payload: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    inferred = {
        key: payload[key]
        for key in (
            "case_filter_count",
            "collection_graph_version",
            "concurrency",
            "limit",
            "mode",
            "thresholds",
            "token_budget",
            "tool_choice",
            "tool_source",
            "top_k",
        )
        if key in payload
    }
    if config:
        inferred.update(config)
    return inferred


def _summary(payload: dict[str, Any], source_type: str) -> dict[str, Any]:
    if isinstance(payload.get("summary"), dict):
        return dict(payload["summary"])
    if source_type in {"pipeline", "reporter"}:
        return {
            "datasets": [
                {
                    key: dataset.get(key)
                    for key in (
                        "avg_map",
                        "avg_mrr",
                        "avg_ndcg_at_k",
                        "avg_recall_at_k",
                        "baseline_accuracy",
                        "hit_rate",
                        "miss_rate",
                        "name",
                        "query_count",
                        "retrieve_accuracy",
                        "tool_count",
                    )
                    if key in dataset
                }
                for dataset in payload.get("datasets") or []
                if isinstance(dataset, dict)
            ]
        }
    if source_type == "xgen_tool_graph":
        return {
            "pipelines": [
                {
                    "name": pipeline.get("name"),
                    "summary": pipeline.get("summary") or {},
                }
                for pipeline in payload.get("pipelines") or []
                if isinstance(pipeline, dict)
            ],
            **{
                key: payload[key]
                for key in ("improvements", "producer_expansion_lift")
                if key in payload
            },
        }
    return {
        key: payload[key]
        for key in ("gate", "improvements", "scale", "search", "status")
        if key in payload
    }


def _statistics(payload: dict[str, Any], source_type: str) -> dict[str, Any]:
    if source_type not in {"pipeline", "reporter"}:
        return {}
    return {
        "datasets": [
            {
                key: dataset[key]
                for key in (
                    "ci_mrr",
                    "ci_recall",
                    "p_value",
                    "stdev_mrr",
                    "stdev_recall",
                    "t_statistic",
                )
                if key in dataset
            }
            for dataset in payload.get("datasets") or []
            if isinstance(dataset, dict)
        ]
    }


def _model_metadata(payload: dict[str, Any], run_kind: str) -> dict[str, Any]:
    if run_kind != "model":
        return {}
    name = str(payload.get("model") or "")
    return {
        "name": name,
        "provider": "unrecorded",
        "revision": "unrecorded",
    }


def _run_kind(source_type: str, payload: dict[str, Any]) -> str:
    if source_type in {"bfcl_model"} or payload.get("model") not in (None, "", "none"):
        return "model"
    if source_type == "execution":
        return "execution"
    if source_type.startswith("xgen_"):
        return "xgen"
    return "deterministic"


def _status(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").casefold()
    if status in {"failed", "fail", "blocked"}:
        return "failed"
    if status in {"partial", "skipped", "warning"}:
        return "partial"
    return "completed"


def _default_replay_command(source_type: str) -> list[str]:
    modules = {
        "bfcl_model": "benchmarks.bfcl_tool_selection.llm_loop",
        "bfcl_tool_selection": "benchmarks.bfcl_tool_selection.run",
        "pipeline": "benchmarks.run_benchmark",
        "reporter": "benchmarks.run_benchmark",
        "xgen_api_scale": "benchmarks.xgen_api_scale.run",
        "xgen_tool_graph": "benchmarks.xgen_tool_graph.run",
    }
    module = modules.get(source_type)
    return ["python", "-m", module] if module else []


def _case_fingerprint(row: dict[str, Any]) -> str:
    query = str(row.get("query") or "")
    category = str(row.get("category") or "")
    if not query and not category:
        return ""
    digest = hashlib.sha256(f"{category}\0{query}".encode()).hexdigest()[:16]
    return f"legacy-{digest}"


def _to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise TypeError("Legacy report must be a dict, dataclass, or expose to_dict().")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
