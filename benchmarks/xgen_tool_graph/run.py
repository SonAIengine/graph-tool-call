"""Deterministic XGEN-style benchmark for tool graph search quality.

The regular benchmark suite answers "did a retriever put the right tool in
top-K?". XGEN needs a stricter question: did OpenAPI extraction produce IO
contracts, did graph search surface the target, did producer expansion include
the prerequisite tools, and can the public PathSynthesizer bind a plan from the
same graph?

This runner avoids LLM calls on purpose. It is a stable regression harness for
the engine layer; model/tool-calling benchmarks can sit above it.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.metrics import mrr, recall_at_k
from graph_tool_call import __version__
from graph_tool_call.graphify import (
    COLLECTION_GRAPH_VERSION,
    annotate_graphify_metadata,
    build_io_contract,
    expand_candidates_with_producers,
    ingest_openapi_graphify,
    retrieve_graphify,
)
from graph_tool_call.ingest.openapi import ingest_openapi
from graph_tool_call.plan import PathSynthesizer, Plan, PlanSynthesisError
from graph_tool_call.tool_graph import ToolGraph

ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC_PATH = ROOT / "commerce_openapi.json"
DEFAULT_CASES_PATH = ROOT / "cases.json"
DEFAULT_ADMIN_SPEC_PATH = ROOT / "admin_openapi.json"
DEFAULT_ADMIN_CASES_PATH = ROOT / "admin_cases.json"
DEFAULT_WORKFLOW_SPEC_PATH = ROOT / "workflow_openapi.json"
DEFAULT_WORKFLOW_CASES_PATH = ROOT / "workflow_cases.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
SUITE_CONFIGS: dict[str, tuple[Path, Path]] = {
    "commerce": (DEFAULT_SPEC_PATH, DEFAULT_CASES_PATH),
    "admin": (DEFAULT_ADMIN_SPEC_PATH, DEFAULT_ADMIN_CASES_PATH),
    "workflow": (DEFAULT_WORKFLOW_SPEC_PATH, DEFAULT_WORKFLOW_CASES_PATH),
}


@dataclass
class QueryEvaluation:
    case_id: str
    query: str
    expected_target: str
    retrieved: list[str]
    candidates: list[str]
    target_rank: int | None
    target_recall_at_k: float
    target_mrr: float
    producer_recall: float
    candidate_plan_coverage: float
    candidate_binding_support: float
    plan_steps: list[str] = field(default_factory=list)
    plan_exact_match: float = 0.0
    plan_step_recall: float = 0.0
    binding_accuracy: float = 1.0
    user_input_slot_recall: float = 1.0
    evidence_coverage: float = 0.0
    token_budget_used: int = 0
    latency_ms: float = 0.0
    failure_reason: str = ""
    synthesis_diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineEvaluation:
    name: str
    depth: int
    expand_producers: bool
    summary: dict[str, float | int | str]
    cases: list[QueryEvaluation]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_benchmark_graph(
    *,
    spec_path: Path = DEFAULT_SPEC_PATH,
) -> tuple[ToolGraph, dict[str, Any], dict[str, Any]]:
    """Build a graphify graph from the OpenAPI fixture using public contracts."""
    raw_spec = load_json(spec_path)
    tools, _normalized_spec = ingest_openapi(raw_spec)
    operations = _operation_index(raw_spec)

    for tool in tools:
        op = operations.get(tool.name) or {}
        ext = op.get("x-graph-tool-call") or {}
        ai_metadata = dict(ext.get("ai_metadata") or {})
        metadata = dict(tool.metadata or {})
        response_schema = _response_schema(op)
        request_body_schema = _request_body_schema(op)
        parameters = _parameters(op)
        produces, consumes = build_io_contract(
            response_schema=response_schema,
            request_body_schema=request_body_schema,
            parameters=parameters,
            context_field_names=set(ext.get("context_field_names") or []),
            auth_field_names=set(ext.get("auth_field_names") or []),
            paging_field_names=set(ext.get("paging_field_names") or []),
            search_filter_field_names=set(ext.get("search_filter_field_names") or []),
            tool_metadata={"ai_metadata": ai_metadata},
        )
        metadata.update(
            {
                "ai_metadata": ai_metadata,
                "produces": produces,
                "consumes": consumes,
                "source_label": "xgen-commerce-fixture",
            }
        )
        tool.metadata = metadata

    tg, edge_stats = ingest_openapi_graphify(tools, raw_spec=raw_spec)
    graph_payload = annotate_graphify_metadata(
        {
            "graph": tg.graph.to_dict(),
            "tools": {name: tool.to_dict() for name, tool in tg.tools.items()},
            "edge_stats": edge_stats,
        }
    )
    return tg, graph_payload, raw_spec


def run_benchmark(
    *,
    spec_path: Path = DEFAULT_SPEC_PATH,
    cases_path: Path = DEFAULT_CASES_PATH,
    top_k: int | None = None,
    token_budget: int | None = None,
) -> dict[str, Any]:
    cases_doc = load_json(cases_path)
    configured_top_k = int(top_k or cases_doc.get("top_k") or 5)
    configured_budget = int(token_budget or cases_doc.get("token_budget") or 2000)
    tg, graph_payload, _raw_spec = build_benchmark_graph(spec_path=spec_path)
    context_defaults = dict(cases_doc.get("context_defaults") or {})
    cases = list(cases_doc.get("cases") or [])

    pipelines = [
        ("target_only", 0, False),
        ("graph_with_producers", 2, True),
    ]
    evaluated: list[PipelineEvaluation] = []
    for name, depth, expand in pipelines:
        rows = [
            evaluate_case(
                case,
                tg=tg,
                graph_payload=graph_payload,
                context_defaults=context_defaults,
                top_k=configured_top_k,
                depth=depth,
                token_budget=configured_budget,
                expand_producers=expand,
            )
            for case in cases
        ]
        evaluated.append(
            PipelineEvaluation(
                name=name,
                depth=depth,
                expand_producers=expand,
                summary=_summarize(rows, name=name, thresholds=cases_doc.get("thresholds") or {}),
                cases=rows,
            )
        )

    return {
        "benchmark": cases_doc.get("name"),
        "description": cases_doc.get("description"),
        "methodology": "deterministic_engine_contract",
        "model": "none",
        "graph_tool_call_version": __version__,
        "collection_graph_version": COLLECTION_GRAPH_VERSION,
        "top_k": configured_top_k,
        "token_budget": configured_budget,
        "tool_count": len(tg.tools),
        "edge_count": tg.graph.edge_count(),
        "thresholds": cases_doc.get("thresholds") or {},
        "pipelines": [asdict(p) for p in evaluated],
        "improvements": _compare(evaluated),
        "producer_expansion_lift": _producer_expansion_lift(evaluated),
    }


def run_benchmark_suite(
    *,
    suite: str = "commerce",
    top_k: int | None = None,
    token_budget: int | None = None,
) -> dict[str, Any]:
    """Run one named XGEN fixture suite or all suites.

    ``run_benchmark`` remains the low-level entry point for ad-hoc
    ``--spec``/``--cases`` pairs. This helper is the stable product-readiness
    contract: every named suite represents one real XGEN API Collection family.
    """
    if suite == "all":
        return run_all_benchmarks(top_k=top_k, token_budget=token_budget)
    if suite not in SUITE_CONFIGS:
        msg = f"unknown XGEN benchmark suite: {suite!r}"
        raise ValueError(msg)
    spec_path, cases_path = SUITE_CONFIGS[suite]
    report = run_benchmark(
        spec_path=spec_path,
        cases_path=cases_path,
        top_k=top_k,
        token_budget=token_budget,
    )
    report["suite"] = suite
    return report


def run_all_benchmarks(
    *,
    top_k: int | None = None,
    token_budget: int | None = None,
) -> dict[str, Any]:
    """Run all deterministic XGEN fixture families and aggregate graph metrics."""
    suite_reports = [
        run_benchmark_suite(suite=name, top_k=top_k, token_budget=token_budget)
        for name in SUITE_CONFIGS
    ]
    effective_top_k = top_k if top_k is not None else _common_value(suite_reports, "top_k")
    effective_budget = (
        token_budget if token_budget is not None else _common_value(suite_reports, "token_budget")
    )
    graph_summaries = [
        next(p for p in report["pipelines"] if p["name"] == "graph_with_producers")["summary"]
        for report in suite_reports
    ]
    producer_lifts = [report["producer_expansion_lift"] for report in suite_reports]
    aggregate_lift = _aggregate_producer_expansion_lift(producer_lifts)
    total_cases = sum(int(summary.get("cases") or 0) for summary in graph_summaries)
    status = (
        "pass" if all(summary.get("status") == "pass" for summary in graph_summaries) else "fail"
    )
    aggregate_metrics = [
        "target_recall_at_k",
        "mean_target_mrr",
        "producer_recall",
        "candidate_plan_coverage",
        "candidate_binding_support",
        "plan_exact_match",
        "plan_step_recall",
        "binding_accuracy",
        "user_input_slot_recall",
        "evidence_coverage",
        "synthesis_diagnostics_coverage",
        "avg_token_budget_used",
        "avg_latency_ms",
    ]
    summary: dict[str, Any] = {
        "status": status,
        "suite_count": len(suite_reports),
        "fixture_families": list(SUITE_CONFIGS),
        "cases": total_cases,
        "tool_count": sum(int(report["tool_count"]) for report in suite_reports),
        "edge_count": sum(int(report["edge_count"]) for report in suite_reports),
        "synthesis_failure_count": sum(
            int(row.get("synthesis_failure_count") or 0) for row in graph_summaries
        ),
        "user_input_slot_case_count": sum(
            int(row.get("user_input_slot_case_count") or 0) for row in graph_summaries
        ),
        "missing_field_count": sum(
            int(row.get("missing_field_count") or 0) for row in graph_summaries
        ),
    }
    for metric in aggregate_metrics:
        summary[metric] = _weighted_mean(
            (
                float(row.get(metric) or 0.0),
                int(row.get("cases") or 0),
            )
            for row in graph_summaries
        )
    summary.update(
        {
            "producer_expansion_producer_recall_delta": aggregate_lift["producer_recall"]["delta"],
            "producer_expansion_candidate_plan_coverage_delta": aggregate_lift[
                "candidate_plan_coverage"
            ]["delta"],
            "producer_expansion_binding_support_delta": aggregate_lift["candidate_binding_support"][
                "delta"
            ],
            "producer_expansion_lifted_cases": aggregate_lift["lifted_cases"]["any"],
        }
    )

    return {
        "benchmark": "XGEN Tool Graph Benchmark Suites",
        "description": "Deterministic XGEN-style benchmark across API Collection fixture families.",
        "methodology": "deterministic_engine_contract",
        "model": "none",
        "graph_tool_call_version": __version__,
        "collection_graph_version": COLLECTION_GRAPH_VERSION,
        "top_k": effective_top_k,
        "token_budget": effective_budget,
        "summary": summary,
        "producer_expansion_lift": aggregate_lift,
        "suites": suite_reports,
    }


def evaluate_case(
    case: dict[str, Any],
    *,
    tg: ToolGraph,
    graph_payload: dict[str, Any],
    context_defaults: dict[str, Any],
    top_k: int,
    depth: int,
    token_budget: int,
    expand_producers: bool,
) -> QueryEvaluation:
    query = str(case["query"])
    expected_target = str(case["expected_target"])
    expected_producers = set(case.get("expected_producers") or [])
    expected_plan = list(case.get("expected_plan") or [])
    expected_bindings = dict(case.get("expected_bindings") or {})
    expected_slots = {str(v) for v in case.get("expected_user_input_slots") or []}

    start = time.perf_counter()
    retrieval = retrieve_graphify(
        tg,
        query,
        top_k=top_k,
        depth=depth,
        token_budget=token_budget,
        include_evidence=True,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    retrieved = [str(row["name"]) for row in retrieval.get("results") or []]
    # The baseline isolates what happens after a target selector has picked the
    # expected target but before producer expansion adds prerequisite tools.
    candidates = [expected_target] if expected_target in retrieved else retrieved[:1]
    if expand_producers:
        candidates = list(retrieved)
        candidates = expand_candidates_with_producers(
            retrieved,
            graph_payload["tools"],
            max_producers_per_field=3,
        )

    target_rank = _rank_of(retrieved, expected_target)
    target_recall = recall_at_k(retrieved, {expected_target}, top_k)
    target_mrr = mrr(retrieved, {expected_target})
    producer_recall = recall_at_k(candidates, expected_producers, len(candidates))
    candidate_plan_coverage = recall_at_k(candidates, set(expected_plan), len(candidates))
    candidate_binding_support = recall_at_k(
        candidates,
        {str(v) for v in expected_bindings.values()},
        len(candidates),
    )

    plan_steps: list[str] = []
    plan_exact = 0.0
    plan_recall = 0.0
    binding_accuracy = 1.0
    slot_recall = 1.0
    failure_reason = ""
    diagnostics = _base_synthesis_diagnostics(
        target=expected_target,
        stage="target_selection",
        retrieval=retrieval,
        target_rank=target_rank,
    )
    if expected_target in candidates:
        try:
            plan = PathSynthesizer(
                graph_payload,
                context_defaults=context_defaults,
            ).synthesize(
                target=expected_target,
                entities=dict(case.get("entities") or {}),
                goal=query,
            )
            plan_steps = [step.tool for step in plan.steps]
            plan_exact = 1.0 if plan_steps == expected_plan else 0.0
            plan_recall = recall_at_k(plan_steps, set(expected_plan), len(plan_steps))
            binding_accuracy = _binding_accuracy(plan, expected_bindings)
            slot_recall = _slot_recall(plan, expected_slots)
            diagnostics = _plan_synthesis_diagnostics(
                plan,
                retrieval=retrieval,
                target_rank=target_rank,
            )
        except PlanSynthesisError as exc:
            failure = exc.to_dict()
            failure_reason = failure.get("reason", type(exc).__name__)
            diagnostics = _failure_synthesis_diagnostics(
                target=expected_target,
                retrieval=retrieval,
                target_rank=target_rank,
                failure=failure,
            )
        except Exception as exc:  # pragma: no cover - defensive benchmark diagnostics
            failure_reason = type(exc).__name__
            diagnostics = _failure_synthesis_diagnostics(
                target=expected_target,
                retrieval=retrieval,
                target_rank=target_rank,
                failure={
                    "stage": "synthesize",
                    "reason": type(exc).__name__,
                    "message": str(exc),
                },
            )
    else:
        diagnostics["failure"] = {
            "stage": "target_selection",
            "reason": "target_not_in_candidates",
            "message": "expected target was not present in the candidate set",
        }
        failure_reason = "target_not_in_candidates"

    return QueryEvaluation(
        case_id=str(case["id"]),
        query=query,
        expected_target=expected_target,
        retrieved=retrieved,
        candidates=candidates,
        target_rank=target_rank,
        target_recall_at_k=target_recall,
        target_mrr=target_mrr,
        producer_recall=producer_recall,
        candidate_plan_coverage=candidate_plan_coverage,
        candidate_binding_support=candidate_binding_support,
        plan_steps=plan_steps,
        plan_exact_match=plan_exact,
        plan_step_recall=plan_recall,
        binding_accuracy=binding_accuracy,
        user_input_slot_recall=slot_recall,
        evidence_coverage=_evidence_coverage(retrieval),
        token_budget_used=int((retrieval.get("stats") or {}).get("token_budget_used") or 0),
        latency_ms=round(latency_ms, 3),
        failure_reason=failure_reason,
        synthesis_diagnostics=diagnostics,
    )


def _base_synthesis_diagnostics(
    *,
    target: str,
    stage: str,
    retrieval: dict[str, Any],
    target_rank: int | None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "target": target,
        "plan_id": "",
        "selected_producers": [],
        "candidate_signals": {},
        "user_input_slots": [],
        "missing_fields": [],
        "failure": {},
        "retrieval_evidence": _retrieval_evidence(retrieval, target_rank),
    }


def _plan_synthesis_diagnostics(
    plan: Plan,
    *,
    retrieval: dict[str, Any],
    target_rank: int | None,
) -> dict[str, Any]:
    metadata = plan.metadata or {}
    synthesis = metadata.get("synthesis") or {}
    user_input_slots = [
        dict(slot) for slot in metadata.get("user_input_slots") or [] if isinstance(slot, dict)
    ]
    fallbacks = [dict(row) for row in synthesis.get("fallbacks") or [] if isinstance(row, dict)]
    return {
        "stage": "synthesize",
        "target": str(synthesis.get("target") or metadata.get("target") or ""),
        "plan_id": plan.id,
        "step_count": len(plan.steps),
        "selected_producers": [
            dict(row) for row in synthesis.get("selected_producers") or [] if isinstance(row, dict)
        ],
        "candidate_signals": dict(synthesis.get("candidate_signals") or {}),
        "user_input_slots": user_input_slots,
        "missing_fields": _missing_fields_from_slots(user_input_slots, fallbacks),
        "failure": {},
        "retrieval_evidence": _retrieval_evidence(retrieval, target_rank),
    }


def _failure_synthesis_diagnostics(
    *,
    target: str,
    retrieval: dict[str, Any],
    target_rank: int | None,
    failure: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": str(failure.get("stage") or "synthesize"),
        "target": target,
        "plan_id": "",
        "selected_producers": [],
        "candidate_signals": {},
        "user_input_slots": [],
        "missing_fields": _missing_fields_from_failure(failure),
        "failure": dict(failure),
        "retrieval_evidence": _retrieval_evidence(retrieval, target_rank),
    }


def _retrieval_evidence(retrieval: dict[str, Any], target_rank: int | None) -> dict[str, Any]:
    stats = retrieval.get("stats") or {}
    return {
        "target_rank": target_rank,
        "result_count": len(retrieval.get("results") or []),
        "token_budget_used": int(stats.get("token_budget_used") or 0),
        "seed_count": len(stats.get("seeds") or []),
        "expanded_from_count": len(stats.get("expanded_from") or []),
    }


def _missing_fields_from_slots(
    user_input_slots: list[dict[str, Any]],
    fallbacks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback_by_key = {
        (
            str(row.get("tool") or ""),
            str(row.get("field_name") or ""),
        ): row
        for row in fallbacks
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for slot in user_input_slots:
        key = (
            str(slot.get("tool") or ""),
            str(slot.get("field_name") or ""),
        )
        fallback = fallback_by_key.get(key) or {}
        out.append(
            {
                "stage": "synthesize",
                "tool": key[0],
                "field_name": key[1],
                "step_id": str(slot.get("step_id") or ""),
                "semantic_tag": str(fallback.get("semantic_tag") or ""),
                "reason": str(fallback.get("reason") or "user_input_required"),
                "cause": str(fallback.get("cause") or ""),
            }
        )
        seen.add(key)
    for key, fallback in fallback_by_key.items():
        if key in seen:
            continue
        out.append(
            {
                "stage": "synthesize",
                "tool": key[0],
                "field_name": key[1],
                "step_id": "",
                "semantic_tag": str(fallback.get("semantic_tag") or ""),
                "reason": str(fallback.get("reason") or "user_input_required"),
                "cause": str(fallback.get("cause") or ""),
            }
        )
    return out


def _missing_fields_from_failure(failure: dict[str, Any]) -> list[dict[str, Any]]:
    field_name = str(failure.get("field_name") or "")
    if not field_name:
        return []
    return [
        {
            "stage": str(failure.get("stage") or "synthesize"),
            "tool": str(failure.get("tool") or ""),
            "field_name": field_name,
            "step_id": "",
            "semantic_tag": str(failure.get("semantic_tag") or ""),
            "reason": str(failure.get("reason") or "synthesis_error"),
            "cause": "",
        }
    ]


def _diagnostics_coverage(diagnostics: dict[str, Any]) -> float:
    if not diagnostics:
        return 0.0
    if not diagnostics.get("stage") or not diagnostics.get("target"):
        return 0.0
    if not isinstance(diagnostics.get("retrieval_evidence"), dict):
        return 0.0
    failure = diagnostics.get("failure") or {}
    if failure and not (failure.get("stage") and failure.get("reason")):
        return 0.0
    return 1.0


def _summarize(
    rows: list[QueryEvaluation],
    *,
    name: str,
    thresholds: dict[str, Any],
) -> dict[str, float | int | str]:
    summary: dict[str, float | int | str] = {
        "pipeline": name,
        "cases": len(rows),
        "target_recall_at_k": _mean(r.target_recall_at_k for r in rows),
        "mean_target_mrr": _mean(r.target_mrr for r in rows),
        "producer_recall": _mean(r.producer_recall for r in rows),
        "candidate_plan_coverage": _mean(r.candidate_plan_coverage for r in rows),
        "candidate_binding_support": _mean(r.candidate_binding_support for r in rows),
        "plan_exact_match": _mean(r.plan_exact_match for r in rows),
        "plan_step_recall": _mean(r.plan_step_recall for r in rows),
        "binding_accuracy": _mean(r.binding_accuracy for r in rows),
        "user_input_slot_recall": _mean(r.user_input_slot_recall for r in rows),
        "evidence_coverage": _mean(r.evidence_coverage for r in rows),
        "synthesis_diagnostics_coverage": _mean(
            _diagnostics_coverage(r.synthesis_diagnostics) for r in rows
        ),
        "synthesis_failure_count": sum(1 for r in rows if r.failure_reason),
        "user_input_slot_case_count": sum(
            1 for r in rows if (r.synthesis_diagnostics or {}).get("user_input_slots")
        ),
        "missing_field_count": sum(
            len((r.synthesis_diagnostics or {}).get("missing_fields") or []) for r in rows
        ),
        "avg_token_budget_used": round(_mean(r.token_budget_used for r in rows), 1),
        "avg_latency_ms": round(_mean(r.latency_ms for r in rows), 3),
    }
    if thresholds:
        checks = [
            metric
            for metric, threshold in thresholds.items()
            if _threshold_passed(summary, metric, float(threshold))
        ]
        summary["thresholds_passed"] = len(checks)
        summary["thresholds_total"] = len(thresholds)
        summary["status"] = "pass" if len(checks) == len(thresholds) else "fail"
    return summary


def _compare(pipelines: list[PipelineEvaluation]) -> dict[str, float]:
    by_name = {p.name: p.summary for p in pipelines}
    base = by_name.get("target_only") or {}
    graph = by_name.get("graph_with_producers") or {}
    metrics = [
        "producer_recall",
        "candidate_plan_coverage",
        "candidate_binding_support",
        "plan_exact_match",
        "plan_step_recall",
        "binding_accuracy",
        "user_input_slot_recall",
    ]
    return {
        f"{metric}_delta": round(float(graph.get(metric, 0.0)) - float(base.get(metric, 0.0)), 6)
        for metric in metrics
    }


def _producer_expansion_lift(pipelines: list[PipelineEvaluation]) -> dict[str, Any]:
    by_name = {p.name: p for p in pipelines}
    base = by_name.get("target_only")
    graph = by_name.get("graph_with_producers")
    if base is None or graph is None:
        return {}

    metrics = [
        "producer_recall",
        "candidate_plan_coverage",
        "candidate_binding_support",
        "plan_exact_match",
        "plan_step_recall",
    ]
    lift: dict[str, Any] = {
        "baseline_pipeline": base.name,
        "expanded_pipeline": graph.name,
        "cases": min(len(base.cases), len(graph.cases)),
        "lifted_cases": _lifted_case_counts(base.cases, graph.cases),
    }
    for metric in metrics:
        before = float(base.summary.get(metric, 0.0))
        after = float(graph.summary.get(metric, 0.0))
        lift[metric] = {
            "before": round(before, 6),
            "after": round(after, 6),
            "delta": round(after - before, 6),
        }
    return lift


def _lifted_case_counts(
    baseline_cases: list[QueryEvaluation],
    expanded_cases: list[QueryEvaluation],
) -> dict[str, int]:
    base_by_id = {row.case_id: row for row in baseline_cases}
    lifted = {
        "producer_recall": 0,
        "candidate_plan_coverage": 0,
        "candidate_binding_support": 0,
        "any": 0,
    }
    for expanded in expanded_cases:
        base = base_by_id.get(expanded.case_id)
        if base is None:
            continue
        producer = expanded.producer_recall > base.producer_recall
        plan = expanded.candidate_plan_coverage > base.candidate_plan_coverage
        binding = expanded.candidate_binding_support > base.candidate_binding_support
        if producer:
            lifted["producer_recall"] += 1
        if plan:
            lifted["candidate_plan_coverage"] += 1
        if binding:
            lifted["candidate_binding_support"] += 1
        if producer or plan or binding:
            lifted["any"] += 1
    return lifted


def _aggregate_producer_expansion_lift(lifts: list[dict[str, Any]]) -> dict[str, Any]:
    active = [lift for lift in lifts if lift]
    total_cases = sum(int(lift.get("cases") or 0) for lift in active)
    out: dict[str, Any] = {
        "baseline_pipeline": "target_only",
        "expanded_pipeline": "graph_with_producers",
        "cases": total_cases,
        "lifted_cases": {
            "producer_recall": sum(
                int((lift.get("lifted_cases") or {}).get("producer_recall") or 0) for lift in active
            ),
            "candidate_plan_coverage": sum(
                int((lift.get("lifted_cases") or {}).get("candidate_plan_coverage") or 0)
                for lift in active
            ),
            "candidate_binding_support": sum(
                int((lift.get("lifted_cases") or {}).get("candidate_binding_support") or 0)
                for lift in active
            ),
            "any": sum(int((lift.get("lifted_cases") or {}).get("any") or 0) for lift in active),
        },
    }
    for metric in (
        "producer_recall",
        "candidate_plan_coverage",
        "candidate_binding_support",
        "plan_exact_match",
        "plan_step_recall",
    ):
        before = _weighted_mean(
            (
                float((lift.get(metric) or {}).get("before") or 0.0),
                int(lift.get("cases") or 0),
            )
            for lift in active
        )
        after = _weighted_mean(
            (
                float((lift.get(metric) or {}).get("after") or 0.0),
                int(lift.get("cases") or 0),
            )
            for lift in active
        )
        out[metric] = {
            "before": before,
            "after": after,
            "delta": round(after - before, 6),
        }
    return out


def _operation_index(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                out[str(operation_id)] = operation
    return out


def _parameters(operation: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in operation.get("parameters") or [] if isinstance(p, dict)]


def _request_body_schema(operation: dict[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody") or {}
    if not isinstance(request_body, dict):
        return {}
    return _content_schema(request_body.get("content") or {})


def _response_schema(operation: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses") or {}
    if not isinstance(responses, dict):
        return {}
    for code in ("200", "201", "default"):
        response = responses.get(code) or {}
        if not isinstance(response, dict):
            continue
        schema = _content_schema(response.get("content") or {})
        if schema:
            return schema
    return {}


def _content_schema(content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict):
        return {}
    media_types = ["application/json", "*/*", *content.keys()]
    for media_type in media_types:
        media = content.get(media_type) or {}
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return {}


def _rank_of(names: list[str], expected: str) -> int | None:
    try:
        return names.index(expected) + 1
    except ValueError:
        return None


def _binding_accuracy(plan: Plan, expected: dict[str, str]) -> float:
    if not expected:
        return 1.0
    step_id_to_tool = {step.id: step.tool for step in plan.steps}
    hits = 0
    for key, expected_source_tool in expected.items():
        tool_name, field_name = key.split(".", 1)
        step = next((s for s in plan.steps if s.tool == tool_name), None)
        if step is None:
            continue
        value = step.args.get(field_name)
        if not isinstance(value, str):
            continue
        source_step_id = _binding_step_id(value)
        if source_step_id and step_id_to_tool.get(source_step_id) == expected_source_tool:
            hits += 1
    return hits / len(expected)


def _binding_step_id(value: str) -> str:
    if not value.startswith("${"):
        return ""
    inner = value[2:].split("}", 1)[0]
    return inner.split(".", 1)[0]


def _slot_recall(plan: Plan, expected_slots: set[str]) -> float:
    if not expected_slots:
        return 1.0
    slots = {
        str(slot.get("field_name") or "")
        for slot in (plan.metadata or {}).get("user_input_slots") or []
        if isinstance(slot, dict)
    }
    return len(slots & expected_slots) / len(expected_slots)


def _evidence_coverage(retrieval: dict[str, Any]) -> float:
    results = retrieval.get("results") or []
    if not results:
        return 0.0
    rows_with_breakdown = sum(1 for row in results if row.get("score_breakdown"))
    has_seed_trace = bool((retrieval.get("stats") or {}).get("seeds"))
    return (rows_with_breakdown / len(results)) if has_seed_trace else 0.0


def _mean(values: Any) -> float:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 6)


def _weighted_mean(values: Any) -> float:
    vals = [(float(value), int(weight)) for value, weight in values if int(weight) > 0]
    if not vals:
        return 0.0
    weight_sum = sum(weight for _value, weight in vals)
    return round(sum(value * weight for value, weight in vals) / weight_sum, 6)


def _common_value(reports: list[dict[str, Any]], key: str) -> Any:
    values = {json.dumps(report.get(key), sort_keys=True) for report in reports}
    if len(values) != 1:
        return None
    return json.loads(next(iter(values)))


def _threshold_passed(
    summary: dict[str, float | int | str],
    metric: str,
    threshold: float,
) -> bool:
    if metric.startswith("max_"):
        value = float(summary.get(metric.removeprefix("max_"), 0.0))
        return value <= threshold
    return float(summary.get(metric, 0.0)) >= threshold


def _print_report(report: dict[str, Any]) -> None:
    if "suites" in report:
        summary = report["summary"]
        print(
            f"{report['benchmark']} "
            f"({summary['suite_count']} suites, {summary['cases']} cases, "
            f"{summary['tool_count']} tools, {summary['edge_count']} edges)"
        )
        print(
            f"model={report['model']} methodology={report['methodology']} "
            f"graph-tool-call={report['graph_tool_call_version']}"
        )
        print(f"status={summary['status']} families={','.join(summary['fixture_families'])}")
        print(
            "  target@K={target:.2f} mrr={mrr_:.2f} producers={prod:.2f} "
            "candidate_plan={cand_plan:.2f} plan_exact={plan:.2f} "
            "bindings={bind:.2f} diagnostics={diag:.2f} latency={latency:.2f}ms".format(
                target=summary["target_recall_at_k"],
                mrr_=summary["mean_target_mrr"],
                prod=summary["producer_recall"],
                cand_plan=summary["candidate_plan_coverage"],
                plan=summary["plan_exact_match"],
                bind=summary["binding_accuracy"],
                diag=summary["synthesis_diagnostics_coverage"],
                latency=summary["avg_latency_ms"],
            )
        )
        lift = report.get("producer_expansion_lift") or {}
        if lift:
            print(
                "  producer expansion lift: producer_recall={prod:+.2f} "
                "candidate_plan={plan:+.2f} binding_support={bind:+.2f} "
                "lifted_cases={cases}".format(
                    prod=lift["producer_recall"]["delta"],
                    plan=lift["candidate_plan_coverage"]["delta"],
                    bind=lift["candidate_binding_support"]["delta"],
                    cases=lift["lifted_cases"]["any"],
                )
            )
        print()
        for suite_report in report["suites"]:
            graph = next(
                p for p in suite_report["pipelines"] if p["name"] == "graph_with_producers"
            )
            row = graph["summary"]
            print(
                "  [{suite}] status={status} cases={cases} target@K={target:.2f} "
                "plan_exact={plan:.2f}".format(
                    suite=suite_report["suite"],
                    status=row.get("status", "n/a"),
                    cases=row["cases"],
                    target=row["target_recall_at_k"],
                    plan=row["plan_exact_match"],
                )
            )
        return

    print(f"{report['benchmark']} ({report['tool_count']} tools, {report['edge_count']} edges)")
    print(
        f"model={report['model']} methodology={report['methodology']} "
        f"graph-tool-call={report['graph_tool_call_version']}"
    )
    print()
    for pipeline in report["pipelines"]:
        summary = pipeline["summary"]
        print(f"[{pipeline['name']}] status={summary.get('status', 'n/a')}")
        print(
            "  target@K={target:.2f} mrr={mrr_:.2f} producers={prod:.2f} "
            "candidate_plan={cand_plan:.2f} plan_exact={plan:.2f} "
            "bindings={bind:.2f} diagnostics={diag:.2f} latency={latency:.2f}ms".format(
                target=summary["target_recall_at_k"],
                mrr_=summary["mean_target_mrr"],
                prod=summary["producer_recall"],
                cand_plan=summary["candidate_plan_coverage"],
                plan=summary["plan_exact_match"],
                bind=summary["binding_accuracy"],
                diag=summary["synthesis_diagnostics_coverage"],
                latency=summary["avg_latency_ms"],
            )
        )
    print()
    print("Improvement over target_only:")
    for key, value in report["improvements"].items():
        print(f"  {key}: {value:+.2f}")
    lift = report.get("producer_expansion_lift") or {}
    if lift:
        print(
            "Producer expansion lift cases: "
            "producer_recall={producer} candidate_plan={plan} "
            "binding_support={binding} any={any_}".format(
                producer=lift["lifted_cases"]["producer_recall"],
                plan=lift["lifted_cases"]["candidate_plan_coverage"],
                binding=lift["lifted_cases"]["candidate_binding_support"],
                any_=lift["lifted_cases"]["any"],
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=[*SUITE_CONFIGS.keys(), "all"],
        default=None,
        help="Run a named built-in XGEN fixture suite. Use 'all' for product-readiness coverage.",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--token-budget", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Print raw JSON report")
    args = parser.parse_args(argv)

    if args.suite:
        report = run_benchmark_suite(
            suite=args.suite,
            top_k=args.top_k,
            token_budget=args.token_budget,
        )
    else:
        report = run_benchmark(
            spec_path=args.spec,
            cases_path=args.cases,
            top_k=args.top_k,
            token_budget=args.token_budget,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    if "suites" in report:
        return 0 if report["summary"].get("status") == "pass" else 1
    graph_pipeline = next(p for p in report["pipelines"] if p["name"] == "graph_with_producers")
    return 0 if graph_pipeline["summary"].get("status") == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
