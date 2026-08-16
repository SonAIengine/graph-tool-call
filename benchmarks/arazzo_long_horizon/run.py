"""Compare long-horizon goal completion with and without Arazzo evidence."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from benchmarks.arazzo_long_horizon.fixtures import FAMILIES, WorkflowFamily, build_fixture
from graph_tool_call import __version__
from graph_tool_call.evaluation import GoalExecutionRecord, ScenarioSpec, evaluate_goal_execution
from graph_tool_call.graphify import (
    apply_arazzo_workflows,
    build_candidate_set,
    ingest_openapi_graphify,
    retrieve_graphify,
    select_target_candidate,
)
from graph_tool_call.ingest.openapi import ingest_openapi
from graph_tool_call.plan import PathSynthesizer, PlanRunner

DEFAULT_LENGTHS = (3, 10, 30)


class WorkflowSandbox:
    """Execute generated workflow operations with strict value handoffs."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._family: WorkflowFamily = fixture["family"]
        self._operations = list(fixture["operations"])
        self._stages = {name: index for index, name in enumerate(self._operations, start=1)}
        self.state = {"completed_stage": 0, "status": "pending"}

    def call_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        stage = self._stages.get(tool)
        if stage is None:
            raise RuntimeError(f"unsupported benchmark tool: {tool}")
        if stage == 1:
            expected = f"SEED-{self._family.id}"
            _require_value(args, "workflowSeed", expected)
        else:
            field = f"handoffToken{stage - 1:02d}"
            _require_value(args, field, f"EVIDENCE-{self._family.id}-{stage - 1:02d}")
        self.state["completed_stage"] = stage
        if stage == len(self._operations):
            self.state["status"] = "complete"
            return {
                self._family.certificate_field: f"CERT-{self._family.id}",
                "status": "complete",
            }
        return {f"stageEvidence{stage:02d}": f"EVIDENCE-{self._family.id}-{stage:02d}"}

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state)


def run_benchmark(
    *,
    catalog_size: int = 1000,
    workflow_lengths: tuple[int, ...] = DEFAULT_LENGTHS,
    top_k: int = 8,
    token_budget: int = 2048,
) -> dict[str, Any]:
    """Run paired no-workflow/Arazzo conditions for each horizon tier."""

    if len(workflow_lengths) > len(FAMILIES):
        raise ValueError("workflow_lengths cannot exceed available unseen families")
    rows: list[dict[str, Any]] = []
    for family, length in zip(FAMILIES, workflow_lengths):
        fixture = build_fixture(family, workflow_length=length, catalog_size=catalog_size)
        baseline = _run_condition(
            fixture,
            use_arazzo=False,
            top_k=top_k,
            token_budget=token_budget,
        )
        enriched = _run_condition(
            fixture,
            use_arazzo=True,
            top_k=top_k,
            token_budget=token_budget,
        )
        rows.append(
            {
                "id": fixture["scenario"]["id"],
                "family": family.id,
                "workflow_length": length,
                "catalog_size": catalog_size,
                "baseline": baseline,
                "with_arazzo": enriched,
                "lift": _condition_lift(baseline, enriched),
            }
        )

    summary = _summarize(rows)
    return {
        "benchmark": "Arazzo Long-Horizon Paired Evaluation",
        "methodology": "paired_deterministic_retrieve_plan_execute_goal_state",
        "model": "none",
        "graph_tool_call_version": __version__,
        "catalog_size": catalog_size,
        "workflow_lengths": list(workflow_lengths),
        "top_k": top_k,
        "token_budget": token_budget,
        "summary": summary,
        "cases": rows,
        "limitations": [
            "The benchmark isolates engine behavior and does not test independent LLM reasoning.",
            "Generated catalogs are contract-distinct synthetic fixtures, not production APIs.",
            (
                "Arazzo evidence is supplied explicitly; workflow discovery without Arazzo "
                "is the baseline."
            ),
        ],
    }


def _run_condition(
    fixture: dict[str, Any],
    *,
    use_arazzo: bool,
    top_k: int,
    token_budget: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    tools, _ = ingest_openapi(fixture["openapi"])
    # Match the public collection-artifact defaults: request contracts are
    # promoted for planning, while unrelated raw response leaves stay out of
    # the search index. Arazzo then supplies only the explicit runtime aliases.
    graph, edge_stats = ingest_openapi_graphify(tools, promote_contract_signals=True)
    workflow_summary: dict[str, Any] = {}
    if use_arazzo:
        workflow_summary = apply_arazzo_workflows(graph, fixture["arazzo"])
    build_latency_ms = (time.perf_counter() - started) * 1000
    graph_payload = {
        "graph": graph.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in graph.tools.items()},
    }

    scenario = ScenarioSpec.from_dict(fixture["scenario"])
    started = time.perf_counter()
    retrieval = retrieve_graphify(
        graph,
        scenario.query,
        top_k=top_k,
        depth=0,
        token_budget=token_budget,
        include_evidence=True,
    )
    retrieval_latency_ms = (time.perf_counter() - started) * 1000
    retrieved = [str(row["name"]) for row in retrieval.get("results") or []]
    selector = select_target_candidate(
        scenario.query,
        retrieved,
        graph_payload["tools"],
        retrieval_results=list(retrieval.get("results") or []),
    )
    selected_target = str(selector.get("selected_target") or "")
    candidates: list[str] = []
    plan = None
    trace = None
    failure: dict[str, str] = {}
    sandbox = WorkflowSandbox(fixture)

    started = time.perf_counter()
    if selected_target:
        expanded = build_candidate_set(
            retrieved,
            graph_payload["tools"],
            expansion_seed=[selected_target],
            max_producers_per_field=1,
            max_hops=len(fixture["operations"]) + 1,
        )
        candidates = [str(name) for name in expanded.get("candidates") or []]
        try:
            plan = PathSynthesizer(
                graph_payload,
                max_depth=len(fixture["operations"]) + 1,
            ).synthesize(
                target=selected_target,
                entities=dict(fixture["entities"]),
                goal=scenario.query,
            )
            trace = PlanRunner(sandbox.call_tool, binding_recovery=True).run(
                plan,
                input_context=dict(fixture["entities"]),
            )
        except Exception as exc:  # noqa: BLE001 - benchmark records stage failures
            failure = {"reason": type(exc).__name__, "message": str(exc)}
    plan_execute_latency_ms = (time.perf_counter() - started) * 1000

    planned_tools = tuple(str(step.tool) for step in (getattr(plan, "steps", ()) or ()))
    if trace is None:
        record = GoalExecutionRecord(
            calls=(),
            success=False,
            retrieved_tools=tuple(retrieved),
            candidate_tools=tuple(candidates),
            planned_tools=planned_tools,
            final_state=sandbox.snapshot(),
        )
    else:
        record = GoalExecutionRecord.from_execution_trace(
            trace,
            plan=plan,
            retrieved_tools=retrieved,
            candidate_tools=candidates,
            final_state=sandbox.snapshot(),
            schema_valid=True,
        )
    evaluation = evaluate_goal_execution(scenario, record)
    expected = list(fixture["operations"])
    executed = [call.tool for call in record.calls]
    target = expected[-1]
    return {
        "use_arazzo": use_arazzo,
        "tool_count": len(graph.tools),
        "edge_count": graph.graph.edge_count(),
        "edge_stats": edge_stats,
        "workflow_summary": workflow_summary,
        "target_hit_at_k": float(target in retrieved),
        "selected_target_exact": float(selected_target == target),
        "selected_target": selected_target,
        "retrieved_tools": retrieved,
        "candidate_count": len(candidates),
        "planned_call_count": len(planned_tools),
        "executed_call_count": len(executed),
        "plan_order_exact": float(list(planned_tools) == expected),
        "execution_order_exact": float(executed == expected),
        "planned_tools": list(planned_tools),
        "executed_tools": executed,
        "runner_success": bool(record.success),
        "failure": failure,
        "evaluation": evaluation.to_dict(),
        "latency_ms": {
            "build": round(build_latency_ms, 3),
            "retrieve": round(retrieval_latency_ms, 3),
            "plan_execute": round(plan_execute_latency_ms, 3),
        },
        "token_budget_used": int(
            retrieval.get("token_budget_used")
            or (retrieval.get("stats") or {}).get("token_budget_used")
            or 0
        ),
    }


def _condition_lift(baseline: dict[str, Any], enriched: dict[str, Any]) -> dict[str, float]:
    baseline_metrics = baseline["evaluation"]["metrics"]
    enriched_metrics = enriched["evaluation"]["metrics"]
    names = (
        "goal_completion",
        "candidate_required_tool_recall",
        "plan_required_tool_recall",
        "execution_required_tool_recall",
        "dependency_order_accuracy",
        "binding_accuracy",
    )
    return {
        name: round(
            float(enriched_metrics.get(name) or 0) - float(baseline_metrics.get(name) or 0),
            6,
        )
        for name in names
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = [row["baseline"] for row in rows]
    enriched = [row["with_arazzo"] for row in rows]

    def average(items: list[dict[str, Any]], path: tuple[str, ...]) -> float:
        values: list[float] = []
        for item in items:
            value: Any = item
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            values.append(float(value or 0))
        return round(sum(values) / len(values), 6) if values else 0.0

    with_arazzo = {
        "target_hit_at_k": average(enriched, ("target_hit_at_k",)),
        "selected_target_exact": average(enriched, ("selected_target_exact",)),
        "candidate_required_tool_recall": average(
            enriched,
            ("evaluation", "metrics", "candidate_required_tool_recall"),
        ),
        "plan_required_tool_recall": average(
            enriched,
            ("evaluation", "metrics", "plan_required_tool_recall"),
        ),
        "execution_required_tool_recall": average(
            enriched,
            ("evaluation", "metrics", "execution_required_tool_recall"),
        ),
        "goal_completion_rate": average(enriched, ("evaluation", "metrics", "goal_completion")),
        "plan_order_exact": average(enriched, ("plan_order_exact",)),
        "execution_order_exact": average(enriched, ("execution_order_exact",)),
        "binding_accuracy": average(enriched, ("evaluation", "metrics", "binding_accuracy")),
        "token_budget_used": {
            "average": average(enriched, ("token_budget_used",)),
            "max": max((int(item.get("token_budget_used") or 0) for item in enriched), default=0),
        },
        "latency_ms": {
            stage: _latency_percentiles(enriched, stage)
            for stage in ("build", "retrieve", "plan_execute")
        },
    }
    without_arazzo = {
        "goal_completion_rate": average(baseline, ("evaluation", "metrics", "goal_completion")),
        "plan_order_exact": average(baseline, ("plan_order_exact",)),
        "binding_accuracy": average(baseline, ("evaluation", "metrics", "binding_accuracy")),
    }
    gates = {
        "target_hit_at_k": with_arazzo["target_hit_at_k"] == 1.0,
        "selected_target_exact": with_arazzo["selected_target_exact"] == 1.0,
        "candidate_required_tool_recall": (with_arazzo["candidate_required_tool_recall"] == 1.0),
        "plan_required_tool_recall": with_arazzo["plan_required_tool_recall"] == 1.0,
        "execution_required_tool_recall": (with_arazzo["execution_required_tool_recall"] == 1.0),
        "goal_completion": with_arazzo["goal_completion_rate"] == 1.0,
        "plan_order_exact": with_arazzo["plan_order_exact"] == 1.0,
        "execution_order_exact": with_arazzo["execution_order_exact"] == 1.0,
        "binding_accuracy": with_arazzo["binding_accuracy"] == 1.0,
        "positive_goal_lift": (
            with_arazzo["goal_completion_rate"] > without_arazzo["goal_completion_rate"]
        ),
    }
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "case_count": len(rows),
        "with_arazzo": with_arazzo,
        "without_arazzo": without_arazzo,
        "goal_completion_lift": round(
            with_arazzo["goal_completion_rate"] - without_arazzo["goal_completion_rate"], 6
        ),
        "gates": gates,
    }


def _latency_percentiles(items: list[dict[str, Any]], stage: str) -> dict[str, float]:
    values = sorted(float(item.get("latency_ms", {}).get(stage) or 0) for item in items)
    return {
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _require_value(args: dict[str, Any], field: str, expected: str) -> None:
    if args.get(field) != expected:
        raise ValueError(f"invalid or missing {field}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-size", type=int, default=1000)
    parser.add_argument("--lengths", default="3,10,30")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=2048)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    lengths = tuple(int(value) for value in args.lengths.split(",") if value.strip())
    report = run_benchmark(
        catalog_size=args.catalog_size,
        workflow_lengths=lengths,
        top_k=args.top_k,
        token_budget=args.token_budget,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        summary = report["summary"]
        print(
            f"{report['benchmark']}: {summary['status']} "
            f"goal {summary['without_arazzo']['goal_completion_rate']:.0%} -> "
            f"{summary['with_arazzo']['goal_completion_rate']:.0%}"
        )
        for row in report["cases"]:
            print(
                f"- {row['family']} {row['workflow_length']} steps / {row['catalog_size']} tools: "
                f"plan={row['with_arazzo']['plan_order_exact']:.0f}, "
                f"binding={row['with_arazzo']['evaluation']['metrics']['binding_accuracy']:.0f}, "
                f"goal={'pass' if row['with_arazzo']['evaluation']['goal_completed'] else 'fail'}"
            )
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
