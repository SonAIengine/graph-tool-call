#!/usr/bin/env python3
"""Recovery benchmark for the PlanRunner failure-recovery loop (A-P0-1).

Measures how often a plan still completes when the underlying tools misbehave
— transient (flaky) failures that a retry should absorb, and permanent
producer failures that a replan should route around — compared against the
v1 ``on_error='abort'`` baseline that gives up on the first error.

No network, no LLM: a synthetic multi-producer graph + a fault-injecting
``call_tool`` decorator. Deterministic, stdlib-only, runnable as::

    python -m benchmarks.run_recovery_benchmark
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from graph_tool_call.plan import (
    PlanCompleted,
    PlanRepairer,
    PlanRunner,
    RetryPolicy,
)
from graph_tool_call.plan.synthesizer import PathSynthesizer

# ---------------------------------------------------------------------------
# fault injection
# ---------------------------------------------------------------------------


def fault_injecting_caller(
    outputs: dict[str, Any],
    *,
    fail_perm: set[str] | None = None,
    fail_times: dict[str, int] | None = None,
) -> Callable[[str, dict[str, Any]], Any]:
    """Wrap a set of canned tool outputs with fault injection.

    ``fail_perm`` tools always raise (models an endpoint that is down / a
    producer whose auth is broken). ``fail_times`` tools raise the given
    number of times, then recover (models a flaky endpoint / rate limit).
    """
    fail_perm = set(fail_perm or set())
    remaining = dict(fail_times or {})

    def call(name: str, args: dict[str, Any]) -> Any:
        if name in fail_perm:
            raise RuntimeError(f"{name}: injected permanent failure")
        if remaining.get(name, 0) > 0:
            remaining[name] -= 1
            raise RuntimeError(f"{name}: injected transient failure")
        return outputs.get(name, {"ok": name, "echoed": args})

    return call


# ---------------------------------------------------------------------------
# synthetic graph — target 'combine' needs 'aId'; two producers can supply it
# ---------------------------------------------------------------------------


def _bench_graph() -> dict[str, Any]:
    def producer() -> dict[str, Any]:
        return {
            "metadata": {
                "method": "GET",
                "path": "/p",
                "consumes": [{"field_name": "seed", "kind": "data", "required": True}],
                "produces": [
                    {"field_name": "aId", "json_path": "$.body.aId", "semantic_tag": "a.id"}
                ],
                "ai_metadata": {"canonical_action": "search", "primary_resource": "a"},
            }
        }

    return {
        "tools": {
            "producerV1": producer(),
            "producerV2": producer(),
            "combine": {
                "metadata": {
                    "method": "GET",
                    "path": "/combine",
                    "consumes": [
                        {
                            "field_name": "aId",
                            "semantic_tag": "a.id",
                            "kind": "data",
                            "required": True,
                        }
                    ],
                    "produces": [{"field_name": "result", "json_path": "$.body.result"}],
                    "ai_metadata": {"canonical_action": "read", "primary_resource": "a"},
                }
            },
        }
    }


_OUTPUTS = {
    "producerV1": {"body": {"aId": "V1"}},
    "producerV2": {"body": {"aId": "V2"}},
    "combine": {"body": {"result": "OK"}},
}


@dataclass
class Scenario:
    name: str
    fail_perm: set[str]
    fail_times: dict[str, int]
    description: str


def _scenarios() -> list[Scenario]:
    return [
        Scenario("clean", set(), {}, "장애 없음 (기준선)"),
        Scenario(
            "transient_producer", set(), {"producerV1": 2}, "producer 2회 flaky → retry 로 흡수"
        ),
        Scenario("transient_target", set(), {"combine": 1}, "target flaky → retry 로 흡수"),
        Scenario("permanent_producer", {"producerV1"}, {}, "producer 영구 장애 → replan 우회"),
    ]


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------


def _run(mode: str, scenario: Scenario) -> bool:
    """Run one scenario in one mode; return True iff the plan completed."""
    graph = _bench_graph()
    syn = PathSynthesizer(graph)
    plan = syn.synthesize(target="combine", entities={"seed": "kw"})
    caller = fault_injecting_caller(
        _OUTPUTS, fail_perm=scenario.fail_perm, fail_times=scenario.fail_times
    )

    if mode == "abort":
        runner = PlanRunner(caller)  # v1 baseline
    else:  # recover
        runner = PlanRunner(
            caller,
            on_error="recover",
            retry_policy=RetryPolicy(max_attempts=3, retry_all=True, backoff_base_ms=0),
            repairer=PlanRepairer(syn, max_repairs=2),
            _sleep=lambda _s: None,
        )

    completed = any(isinstance(e, PlanCompleted) for e in runner.run_stream(plan))
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    scenarios = _scenarios()
    rows = []
    recovered = 0
    baseline_ok = 0
    for sc in scenarios:
        abort_ok = _run("abort", sc)
        recover_ok = _run("recover", sc)
        baseline_ok += int(abort_ok)
        recovered += int(recover_ok)
        rows.append(
            {
                "scenario": sc.name,
                "description": sc.description,
                "baseline_completed": abort_ok,
                "recover_completed": recover_ok,
            }
        )

    total = len(scenarios)
    report = {
        "total_scenarios": total,
        "baseline_completion_rate": round(baseline_ok / total, 3),
        "recovery_completion_rate": round(recovered / total, 3),
        "rows": rows,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("\n=== PlanRunner Recovery Benchmark ===\n")
    print(f"{'scenario':<22}{'baseline':<12}{'recover':<10}description")
    print("-" * 78)
    for r in rows:
        b = "✓" if r["baseline_completed"] else "✗"
        rc = "✓" if r["recover_completed"] else "✗"
        print(f"{r['scenario']:<22}{b:<12}{rc:<10}{r['description']}")
    print("-" * 78)
    print(
        f"baseline completion: {report['baseline_completion_rate']:.0%}   "
        f"recovery completion: {report['recovery_completion_rate']:.0%}"
    )


if __name__ == "__main__":
    main()
