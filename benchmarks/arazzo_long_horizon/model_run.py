"""Run the sealed Arazzo long-horizon gate with a real target-selection model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

from benchmarks.arazzo_long_horizon.fixtures import FAMILIES, WorkflowFamily, build_fixture
from benchmarks.arazzo_long_horizon.run import DEFAULT_LENGTHS, WorkflowSandbox
from benchmarks.paper_model_loop import (
    HTTPModelClient,
    ModelClient,
    build_llm_catalog_index,
    final_selection_messages,
    parse_selector_decision,
    redacted_url,
)
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

MODEL_GATE_REVISION = "arazzo-model-target-selection-v1"


def run_model_benchmark(
    *,
    model: str,
    model_revision: str,
    llm_url: str,
    provider: str = "openai-compatible",
    provider_profile: str = "default",
    api_key_env: str = "OPENAI_API_KEY",
    catalog_size: int = 1000,
    workflow_lengths: tuple[int, ...] = DEFAULT_LENGTHS,
    top_k: int = 8,
    token_budget: int = 2048,
    repeats: int = 1,
    seed: int = 17,
    timeout: int = 180,
    max_selection_tokens: int = 256,
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    """Evaluate model selection and graph-backed execution as separate stages."""

    if len(workflow_lengths) > len(FAMILIES):
        raise ValueError("workflow_lengths cannot exceed available unseen families")
    if repeats <= 0:
        raise ValueError("repeats must be greater than zero")
    if model_client is None:
        extra_body = _provider_options(provider_profile)
        model_client = HTTPModelClient(
            model=model,
            url=llm_url,
            provider=provider,
            api_key_env=api_key_env,
            extra_body=extra_body,
        )

    rows: list[dict[str, Any]] = []
    for repeat in range(repeats):
        for family_index, (family, length) in enumerate(
            zip(FAMILIES, workflow_lengths, strict=False)
        ):
            fixture = build_fixture(family, workflow_length=length, catalog_size=catalog_size)
            rows.append(
                _run_model_case(
                    fixture,
                    repeat=repeat,
                    paired_seed=seed + repeat * len(workflow_lengths) + family_index,
                    top_k=top_k,
                    token_budget=token_budget,
                    timeout=timeout,
                    max_selection_tokens=max_selection_tokens,
                    model_client=model_client,
                )
            )

    summary = _summarize(rows)
    return {
        "benchmark": "Arazzo Long-Horizon Model-in-the-Loop Evaluation",
        "methodology": "retrieve_model_select_guard_plan_execute_goal_state",
        "methodology_revision": MODEL_GATE_REVISION,
        "graph_tool_call_version": __version__,
        "model": {
            "name": model,
            "revision": model_revision,
            "provider": provider,
            "provider_profile": provider_profile,
            "endpoint": redacted_url(llm_url),
        },
        "catalog_size": catalog_size,
        "workflow_lengths": list(workflow_lengths),
        "top_k": top_k,
        "token_budget": token_budget,
        "repeats": repeats,
        "seed": seed,
        "summary": summary,
        "cases": rows,
        "limitations": [
            (
                "The model selects the final target from graph-tool-call's retrieved Top-K; "
                "it is not shown evaluator gold or the complete 1,000-tool catalog."
            ),
            (
                "Arazzo supplies the prerequisite order and runtime bindings after target "
                "selection; the model does not independently enumerate all 30 calls."
            ),
            "Generated catalogs are contract-distinct synthetic fixtures, not production APIs.",
        ],
    }


def _run_model_case(
    fixture: dict[str, Any],
    *,
    repeat: int,
    paired_seed: int,
    top_k: int,
    token_budget: int,
    timeout: int,
    max_selection_tokens: int,
    model_client: ModelClient,
) -> dict[str, Any]:
    family: WorkflowFamily = fixture["family"]
    scenario = ScenarioSpec.from_dict(fixture["scenario"])
    tools, _ = ingest_openapi(fixture["openapi"])
    graph, edge_stats = ingest_openapi_graphify(tools, promote_contract_signals=True)
    workflow_summary = apply_arazzo_workflows(graph, fixture["arazzo"])
    graph_payload = {
        "graph": graph.graph.to_dict(),
        "tools": {name: tool.to_dict() for name, tool in graph.tools.items()},
    }

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
    retrieval_rows = list(retrieval.get("results") or [])
    retrieved = [str(row["name"]) for row in retrieval_rows]
    serialized_catalog = _serialize_candidate_catalog(graph.tools, retrieved)

    model_response = model_client.complete(
        final_selection_messages(
            scenario.query,
            serialized_catalog,
            max_selected_tools=1,
        ),
        seed=paired_seed,
        timeout=timeout,
        max_tokens=max_selection_tokens,
    )
    decision = parse_selector_decision(model_response.content)
    llm_target = decision.target_tool
    reason_codes = list(decision.reason_codes)
    if model_response.error:
        reason_codes.append("selection_model_call_failed")
    if llm_target and llm_target not in retrieved:
        reason_codes.append("selector_tool_not_in_catalog")

    selector = select_target_candidate(
        scenario.query,
        retrieved,
        graph_payload["tools"],
        retrieval_results=retrieval_rows,
        llm_target=llm_target or None,
    )
    selected_target = str(selector.get("selected_target") or "")
    expected = list(fixture["operations"])
    target = expected[-1]

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
            max_hops=len(expected) + 1,
        )
        candidates = [str(name) for name in expanded.get("candidates") or []]
        try:
            plan = PathSynthesizer(graph_payload, max_depth=len(expected) + 1).synthesize(
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
    executed = [call.tool for call in record.calls]
    return {
        "case_id": f"{scenario.id}::repeat-{repeat}",
        "family": family.id,
        "workflow_length": len(expected),
        "catalog_size": len(graph.tools),
        "paired_seed": paired_seed,
        "query": scenario.query,
        "tool_count": len(graph.tools),
        "edge_count": graph.graph.edge_count(),
        "edge_stats": edge_stats,
        "workflow_summary": workflow_summary,
        "target_hit_at_k": float(target in retrieved),
        "llm_target": llm_target,
        "llm_target_exact": float(llm_target == target),
        "llm_target_in_catalog": float(llm_target in retrieved),
        "selected_target": selected_target,
        "selected_target_exact": float(selected_target == target),
        "selector_overrode_llm": bool(selector.get("overrode_llm")),
        "selector_reason_codes": list(selector.get("reason_codes") or []),
        "retrieved_tools": retrieved,
        "candidate_catalog_sha256": hashlib.sha256(serialized_catalog.encode()).hexdigest(),
        "model_response": model_response.to_dict(),
        "model_reason_codes": list(dict.fromkeys(reason_codes)),
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
            "retrieve": round(retrieval_latency_ms, 3),
            "model_select": round(model_response.latency_ms, 3),
            "plan_execute": round(plan_execute_latency_ms, 3),
        },
        "usage": {
            "input_tokens": model_response.input_tokens,
            "output_tokens": model_response.output_tokens,
            "retrieval_token_budget_used": int(
                retrieval.get("token_budget_used")
                or (retrieval.get("stats") or {}).get("token_budget_used")
                or 0
            ),
        },
    }


def _serialize_candidate_catalog(tools_by_name: dict[str, Any], names: list[str]) -> str:
    entries_by_name = {entry["name"]: entry for entry in build_llm_catalog_index(tools_by_name)}
    entries = [entries_by_name[name] for name in names if name in entries_by_name]
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _provider_options(provider_profile: str) -> dict[str, Any]:
    if provider_profile == "deepseek":
        return {
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
    if provider_profile == "default":
        return {}
    raise ValueError("provider_profile must be default or deepseek")


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def average(path: tuple[str, ...]) -> float:
        values: list[float] = []
        for row in rows:
            value: Any = row
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            values.append(float(value or 0))
        return round(sum(values) / len(values), 6) if values else 0.0

    metrics = {
        "target_hit_at_k": average(("target_hit_at_k",)),
        "llm_target_exact": average(("llm_target_exact",)),
        "llm_target_in_catalog": average(("llm_target_in_catalog",)),
        "selected_target_exact": average(("selected_target_exact",)),
        "plan_required_tool_recall": average(
            ("evaluation", "metrics", "plan_required_tool_recall")
        ),
        "execution_required_tool_recall": average(
            ("evaluation", "metrics", "execution_required_tool_recall")
        ),
        "plan_order_exact": average(("plan_order_exact",)),
        "execution_order_exact": average(("execution_order_exact",)),
        "binding_accuracy": average(("evaluation", "metrics", "binding_accuracy")),
        "goal_completion_rate": average(("evaluation", "metrics", "goal_completion")),
    }
    gates = {name: value == 1.0 for name, value in metrics.items()}
    return {
        "status": "pass" if all(gates.values()) else "fail",
        "case_count": len(rows),
        "metrics": metrics,
        "gates": gates,
        "selector_override_rate": average(("selector_overrode_llm",)),
        "latency_ms": {
            stage: _latency_percentiles(rows, stage)
            for stage in ("retrieve", "model_select", "plan_execute")
        },
        "usage": {
            "input_tokens": sum(int(row["usage"]["input_tokens"]) for row in rows),
            "output_tokens": sum(int(row["usage"]["output_tokens"]) for row in rows),
        },
    }


def _latency_percentiles(rows: list[dict[str, Any]], stage: str) -> dict[str, float]:
    values = sorted(float(row["latency_ms"][stage]) for row in rows)
    return {"p50": round(_percentile(values, 0.50), 3), "p95": round(_percentile(values, 0.95), 3)}


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--provider", default="openai-compatible")
    parser.add_argument("--provider-profile", choices=("default", "deepseek"), default="default")
    parser.add_argument("--llm-url", required=True)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--catalog-size", type=int, default=1000)
    parser.add_argument("--lengths", default="3,10,30")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--token-budget", type=int, default=2048)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-selection-tokens", type=int, default=256)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    lengths = tuple(int(value) for value in args.lengths.split(",") if value.strip())
    report = run_model_benchmark(
        model=args.model,
        model_revision=args.model_revision,
        llm_url=args.llm_url,
        provider=args.provider,
        provider_profile=args.provider_profile,
        api_key_env=args.api_key_env,
        catalog_size=args.catalog_size,
        workflow_lengths=lengths,
        top_k=args.top_k,
        token_budget=args.token_budget,
        repeats=args.repeats,
        seed=args.seed,
        timeout=args.timeout,
        max_selection_tokens=args.max_selection_tokens,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        summary = report["summary"]
        metrics = summary["metrics"]
        print(
            f"{report['benchmark']}: {summary['status']} "
            f"model target={metrics['llm_target_exact']:.0%}, "
            f"final target={metrics['selected_target_exact']:.0%}, "
            f"goal={metrics['goal_completion_rate']:.0%}"
        )
        for row in report["cases"]:
            print(
                f"- {row['family']} {row['workflow_length']} steps / "
                f"{row['catalog_size']} tools: llm={row['llm_target_exact']:.0f}, "
                f"final={row['selected_target_exact']:.0f}, "
                f"goal={'pass' if row['evaluation']['goal_completed'] else 'fail'}"
            )
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
