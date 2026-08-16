"""Run natural-language requests through retrieval, planning, and execution.

Gold milestones are used only after execution by the goal evaluator. They are
never passed to retrieval, target selection, PathSynthesizer, or PlanRunner.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from benchmarks.xgen_tool_graph.run import DEFAULT_SPEC_PATH, build_benchmark_graph, load_json
from graph_tool_call import __version__
from graph_tool_call.evaluation import GoalExecutionRecord, ScenarioSpec, evaluate_goal_execution
from graph_tool_call.graphify import (
    build_candidate_set,
    retrieve_graphify,
    target_action_priority_for_query,
)
from graph_tool_call.plan import PathSynthesizer, PlanRunner

ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIOS_PATH = ROOT / "scenarios.json"


class CommerceSandbox:
    """Resettable deterministic API world for fast goal-completion checks."""

    def __init__(self, initial_state: dict[str, Any]) -> None:
        self.state = copy.deepcopy(initial_state)
        self._handlers = {
            "searchProducts": self._call_search_products,
            "getProductDetail": self._call_get_product_detail,
            "getInventory": self._call_get_inventory,
            "getCart": self._call_get_cart,
            "addCartItem": self._call_add_cart_item,
            "validateCoupon": self._call_validate_coupon,
            "checkoutCart": self._call_checkout_cart,
            "findOrders": self._call_find_orders,
            "getOrderDetail": self._call_get_order_detail,
            "getShipmentTracking": self._call_get_shipment_tracking,
            "createProductReview": self._call_create_product_review,
        }

    def call_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(tool)
        if handler is None:
            raise RuntimeError(f"unsupported sandbox tool: {tool}")
        return handler(dict(args))

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def _call_search_products(self, args: dict[str, Any]) -> dict[str, Any]:
        _require(args, "q")
        return {
            "items": [
                {
                    "productId": "P100",
                    "productName": str(args["q"]),
                    "skuId": "SKU100",
                    "price": 100.0,
                }
            ]
        }

    def _call_get_product_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "productId", "P100")
        return {
            "productId": "P100",
            "productName": "fixture product",
            "skuOptions": [{"skuId": "SKU100", "stockQty": 12}],
        }

    def _call_get_inventory(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "skuId", "SKU100")
        return {"skuId": "SKU100", "stockQty": 12, "available": True}

    def _call_get_cart(self, args: dict[str, Any]) -> dict[str, Any]:
        _require(args, "userId")
        return copy.deepcopy(self.state["cart"])

    def _call_add_cart_item(self, args: dict[str, Any]) -> dict[str, Any]:
        _require(args, "userId", "skuId", "quantity")
        _require_value(args, "skuId", "SKU100")
        if not isinstance(args["quantity"], int) or args["quantity"] < 1:
            raise ValueError("quantity must be a positive integer")
        self.state["cart"]["items"].append({"skuId": args["skuId"], "quantity": args["quantity"]})
        return {"cartItemId": "CI100", "skuId": args["skuId"]}

    def _call_validate_coupon(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "couponCode", "WELCOME20")
        return {
            "couponValidationId": "CV100",
            "couponCode": "WELCOME20",
            "discountAmount": 20.0,
            "eligible": True,
        }

    def _call_checkout_cart(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "cartId", "cart-1")
        _require_value(args, "couponValidationId", "CV100")
        _require(args, "paymentMethod")
        self.state["orders"]["O200"] = {
            "orderNo": "O200",
            "status": "paid",
            "paymentMethod": args["paymentMethod"],
        }
        return {"orderNo": "O200", "paymentId": "PAY100"}

    def _call_find_orders(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "customerEmail", "buyer@example.com")
        return {"orders": [copy.deepcopy(self.state["orders"]["O100"])]}

    def _call_get_order_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        _require(args, "orderNo")
        order = self.state["orders"].get(str(args["orderNo"]))
        if not order:
            raise ValueError("unknown orderNo")
        return copy.deepcopy(order)

    def _call_get_shipment_tracking(self, args: dict[str, Any]) -> dict[str, Any]:
        _require_value(args, "shipmentId", "S100")
        return {"shipmentId": "S100", "trackingStatus": "in_transit", "eta": "2026-08-18"}

    def _call_create_product_review(self, args: dict[str, Any]) -> dict[str, Any]:
        _require(args, "userId", "productId", "rating", "comment")
        _require_value(args, "productId", "P100")
        review = {
            "reviewId": "R100",
            "productId": args["productId"],
            "rating": args["rating"],
            "comment": args["comment"],
        }
        self.state["reviews"].append(review)
        return {"reviewId": review["reviewId"], "productId": review["productId"]}


def run_benchmark(
    *,
    scenarios_path: Path = DEFAULT_SCENARIOS_PATH,
    spec_path: Path = DEFAULT_SPEC_PATH,
) -> dict[str, Any]:
    document = load_json(scenarios_path)
    graph, graph_payload, _spec = build_benchmark_graph(spec_path=spec_path)
    top_k = int(document.get("top_k") or 5)
    token_budget = int(document.get("token_budget") or 2048)
    context_defaults = dict(document.get("context_defaults") or {})
    initial_state = dict(document.get("initial_state") or {})
    rows = [
        _run_case(
            case,
            graph=graph,
            graph_payload=graph_payload,
            top_k=top_k,
            token_budget=token_budget,
            context_defaults=context_defaults,
            initial_state=initial_state,
        )
        for case in document.get("cases") or []
    ]
    completed = sum(bool(row["evaluation"]["goal_completed"]) for row in rows)
    return {
        "benchmark": document.get("name"),
        "description": document.get("description"),
        "methodology": "natural_language_retrieve_plan_execute_goal_state",
        "model": "none",
        "graph_tool_call_version": __version__,
        "scenario_count": len(rows),
        "tool_count": len(graph.tools),
        "edge_count": graph.graph.edge_count(),
        "summary": _summarize(rows, completed=completed),
        "cases": rows,
    }


def _run_case(
    case: dict[str, Any],
    *,
    graph: Any,
    graph_payload: dict[str, Any],
    top_k: int,
    token_budget: int,
    context_defaults: dict[str, Any],
    initial_state: dict[str, Any],
) -> dict[str, Any]:
    scenario_value = {**case, "initial_state": initial_state}
    scenario = ScenarioSpec.from_dict(scenario_value)
    retrieval = retrieve_graphify(
        graph,
        scenario.query,
        top_k=top_k,
        depth=0,
        token_budget=token_budget,
        include_evidence=True,
    )
    retrieved = [str(item["name"]) for item in retrieval.get("results") or []]
    selector = build_candidate_set(
        retrieved,
        graph_payload["tools"],
        target_action_priority=target_action_priority_for_query(scenario.query),
        max_hops=0,
    )
    targets = [str(item) for item in selector.get("target_candidates") or []]
    selected_target = targets[0] if targets else ""
    candidates: list[str] = []
    plan = None
    trace = None
    failure: dict[str, Any] = {}
    sandbox = CommerceSandbox(initial_state)
    if selected_target:
        expanded = build_candidate_set(
            retrieved,
            graph_payload["tools"],
            expansion_seed=[selected_target],
            max_producers_per_field=3,
            max_hops=5,
        )
        candidates = [str(item) for item in expanded.get("candidates") or []]
        try:
            plan = PathSynthesizer(
                graph_payload,
                max_depth=5,
                context_defaults=context_defaults,
            ).synthesize(
                target=selected_target,
                entities=dict(case.get("entities") or {}),
                goal=scenario.query,
            )
            trace = PlanRunner(sandbox.call_tool, binding_recovery=True).run(
                plan,
                input_context=dict(case.get("entities") or {}),
            )
        except Exception as exc:  # noqa: BLE001 - benchmark must report stage failures
            failure = {"reason": type(exc).__name__, "message": str(exc)}

    if trace is None:
        record = GoalExecutionRecord(
            calls=(),
            success=False,
            retrieved_tools=tuple(retrieved),
            candidate_tools=tuple(candidates),
            planned_tools=tuple(str(step.tool) for step in (getattr(plan, "steps", ()) or ())),
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
    expected_targets = [
        tool for milestone in scenario.milestones if milestone.target for tool in milestone.tools
    ]
    return {
        "id": scenario.id,
        "query": scenario.query,
        "expected_targets": expected_targets,
        "retrieved_tools": retrieved,
        "selected_target": selected_target,
        "candidate_tools": candidates,
        "planned_tools": list(record.planned_tools),
        "executed_tools": [call.tool for call in record.calls],
        "runner_success": record.success,
        "failure": failure,
        "evaluation": evaluation.to_dict(),
    }


def _summarize(rows: list[dict[str, Any]], *, completed: int) -> dict[str, Any]:
    metric_names = (
        "candidate_required_tool_recall",
        "plan_required_tool_recall",
        "execution_required_tool_recall",
        "dependency_order_accuracy",
        "binding_accuracy",
        "final_state_accuracy",
        "schema_valid_call_rate",
        "extraneous_call_rate",
    )
    metrics: dict[str, Any] = {}
    for name in metric_names:
        values = [
            row["evaluation"]["metrics"].get(name)
            for row in rows
            if row["evaluation"]["metrics"].get(name) is not None
        ]
        metrics[name] = round(sum(values) / len(values), 6) if values else None
    return {
        "status": "pass" if completed == len(rows) else "fail",
        "goal_completion_rate": round(completed / len(rows), 6) if rows else 0.0,
        "completed": completed,
        "cases": len(rows),
        "uncaught_error_count": sum(bool(row["failure"]) for row in rows),
        **metrics,
    }


def _require(args: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in args or args[name] in (None, "")]
    if missing:
        raise ValueError(f"missing required arguments: {', '.join(missing)}")


def _require_value(args: dict[str, Any], name: str, expected: Any) -> None:
    _require(args, name)
    if args[name] != expected:
        raise ValueError(f"invalid {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS_PATH)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_benchmark(scenarios_path=args.scenarios, spec_path=args.spec)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        summary = report["summary"]
        print(
            f"{report['benchmark']}: {summary['completed']}/{summary['cases']} goals "
            f"({summary['goal_completion_rate']:.1%}), status={summary['status']}"
        )
        for row in report["cases"]:
            result = row["evaluation"]
            print(
                f"- {row['id']}: selected={row['selected_target'] or '-'} "
                f"plan={','.join(row['planned_tools']) or '-'} "
                f"goal={'pass' if result['goal_completed'] else 'fail'}"
            )
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
