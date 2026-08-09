"""Build and validate release evidence for the observability trace contract."""

from __future__ import annotations

import argparse
import copy
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_tool_call import __version__
from graph_tool_call.observability import (
    STAGE_DEPENDENCY_CLOSURE,
    STAGE_PLAN,
    STAGE_RETRIEVAL,
    STAGE_RUNNER,
    STAGE_SCHEMA_ADMISSION,
    STAGE_TARGET_SELECTION,
    TraceRecorder,
    record_dependency_closure,
    record_plan,
    record_retrieval_result,
    record_runner_events,
    record_selector_result,
    record_tool_bundle,
    replay_trace,
)

EVIDENCE_SCHEMA_VERSION = "observability-release-evidence-v1"
RELEASE_REF = f"v{__version__}"
DEFAULT_OUTPUT = Path(f"benchmarks/results/releases/{RELEASE_REF}/observability-evidence.json")
MAX_P95_MS_PER_SPAN = 5.0
MAX_SERIALIZED_TRACE_BYTES = 65_536
STAGES = [
    STAGE_RETRIEVAL,
    STAGE_TARGET_SELECTION,
    STAGE_DEPENDENCY_CLOSURE,
    STAGE_SCHEMA_ADMISSION,
    STAGE_PLAN,
    STAGE_RUNNER,
]
_SECRET_MARKERS = (
    "release-secret-token",
    "release-secret-cookie",
    "release-secret-api-key",
    "release@example.com",
)


def _scenario() -> dict[str, Any]:
    return {
        "query": "Find order for release@example.com",
        "Authorization": "Bearer release-secret-token",
        "retrieval": {
            "results": [
                {
                    "name": "getOrder",
                    "score": 0.91,
                    "score_breakdown": {"seed": 0.8, "contract_match": 1.0},
                },
                {
                    "name": "listOrders",
                    "score": 0.73,
                    "score_breakdown": {"graph": 0.73, "graph_expansion": 1.0},
                },
            ],
            "stats": {
                "seeds": ["getOrder"],
                "visited_nodes": 2,
                "visited_edges": 1,
            },
        },
        "selector": {
            "selected_target": "getOrder",
            "llm_target": "listOrders",
            "overrode_llm": True,
            "ambiguous": False,
            "reason_codes": ["llm_target_overridden"],
            "margin": 0.2,
            "policy": "strong_evidence",
            "rank_signals": [
                {
                    "name": "getOrder",
                    "selector_score": 0.9,
                    "original_rank": 1,
                    "selected": True,
                    "evidence": {"contract_match": True},
                },
                {
                    "name": "listOrders",
                    "selector_score": 0.7,
                    "original_rank": 2,
                    "llm_target": True,
                    "evidence": {"shape_match": True},
                },
            ],
        },
        "closure": {
            "target": "getOrder",
            "required_dependencies": ["listOrders"],
            "optional_dependencies": [],
            "unresolved_fields": [],
            "cycles": [],
            "complete": True,
            "evidence": [
                {
                    "producer": "listOrders",
                    "sources": ["api_contract"],
                    "field_key": "order_id",
                }
            ],
        },
        "bundle": {
            "target": "getOrder",
            "required_tools": ["listOrders"],
            "optional_tools": ["searchCustomers"],
            "admitted_tools": ["getOrder", "listOrders"],
            "omitted_tools": ["searchCustomers"],
            "token_budget": {"limit": 256, "used": 230},
            "closure_status": "ready",
        },
        "plan": {
            "id": "plan-release-evidence",
            "steps": [
                {"id": "step-1", "tool": "listOrders", "args": {}},
                {
                    "id": "step-2",
                    "tool": "getOrder",
                    "args": {"api_key": "release-secret-api-key"},
                },
            ],
        },
        "runner_events": [
            {
                "type": "step.completed",
                "step_id": "step-1",
                "tool": "listOrders",
                "cookie": "release-secret-cookie",
            },
            {
                "type": "step.completed",
                "step_id": "step-2",
                "tool": "getOrder",
                "output": {"email": "release@example.com"},
            },
        ],
    }


def _record_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    recorder = TraceRecorder(
        "observability_release_gate",
        trace_id="0123456789abcdef0123456789abcdef",
        attributes={
            "query": payload["query"],
            "Authorization": payload["Authorization"],
        },
    )
    with recorder.start_span(STAGE_RETRIEVAL) as span:
        record_retrieval_result(span, payload["retrieval"])
    with recorder.start_span(STAGE_TARGET_SELECTION) as span:
        record_selector_result(span, payload["selector"])
    with recorder.start_span(STAGE_DEPENDENCY_CLOSURE) as span:
        record_dependency_closure(span, payload["closure"])
    with recorder.start_span(STAGE_SCHEMA_ADMISSION) as span:
        record_tool_bundle(span, payload["bundle"])
    with recorder.start_span(STAGE_PLAN) as span:
        record_plan(span, payload["plan"])
    with recorder.start_span(STAGE_RUNNER) as span:
        record_runner_events(span, payload["runner_events"])
    return recorder.finish().to_dict()


def _measure_overhead(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    payload = _scenario()
    for _ in range(min(5, iterations)):
        _record_scenario(payload)

    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        _record_scenario(payload)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        samples.append(elapsed_ms / len(STAGES))
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "iterations": iterations,
        "spans_per_trace": len(STAGES),
        "per_span_p50_ms": round(statistics.median(ordered), 6),
        "per_span_p95_ms": round(ordered[p95_index], 6),
        "threshold_p95_ms": MAX_P95_MS_PER_SPAN,
    }


def build_observability_evidence(*, iterations: int = 200) -> dict[str, Any]:
    """Return a measured, secret-safe release gate artifact."""

    payload = _scenario()
    original = copy.deepcopy(payload)
    trace = _record_scenario(payload)
    replay = replay_trace(trace)
    replay_again = replay_trace(json.loads(json.dumps(trace)))
    serialized = json.dumps(trace, ensure_ascii=False, sort_keys=True).encode("utf-8")
    secret_scan_passed = not any(marker.encode("utf-8") in serialized for marker in _SECRET_MARKERS)
    overhead = _measure_overhead(iterations)
    checks = {
        "result_invariant": payload == original,
        "replay_deterministic": replay == replay_again,
        "secret_scan_passed": secret_scan_passed,
        "stage_order_complete": replay["stage_order"] == STAGES,
        "reason_coverage_complete": replay["reason_coverage"] == 1.0,
        "serialized_size_bounded": len(serialized) <= MAX_SERIALIZED_TRACE_BYTES,
        "overhead_within_threshold": (overhead["per_span_p95_ms"] < MAX_P95_MS_PER_SPAN),
    }
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "release_ref": RELEASE_REF,
        "graph_tool_call_version": __version__,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.system().lower(),
        },
        "scenario": {
            "stage_order": list(STAGES),
            "decision_count": replay["decision_count"],
            "reason_coverage": replay["reason_coverage"],
            "serialized_trace_bytes": len(serialized),
            "max_serialized_trace_bytes": MAX_SERIALIZED_TRACE_BYTES,
        },
        "overhead": overhead,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
        "replay": {
            "generate_command": "make observability-evidence",
            "check_command": "make observability-evidence-check",
        },
        "limitations": [
            "Local deterministic adapter scenario; no external API or LLM is used.",
            "Latency is a Python microbenchmark and not an end-to-end service SLO.",
            "The gate measures trace capture cost, not backend exporter latency.",
        ],
    }


def validate_observability_evidence(evidence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append("schema_version")
    if evidence.get("release_ref") != RELEASE_REF:
        errors.append("release_ref")
    if evidence.get("graph_tool_call_version") != __version__:
        errors.append("graph_tool_call_version")
    checks = evidence.get("checks")
    if not isinstance(checks, dict) or not checks or not all(checks.values()):
        errors.append("checks")
    overhead = evidence.get("overhead") if isinstance(evidence.get("overhead"), dict) else {}
    if float(overhead.get("per_span_p95_ms") or sys.float_info.max) >= MAX_P95_MS_PER_SPAN:
        errors.append("overhead.per_span_p95_ms")
    if evidence.get("status") != "pass":
        errors.append("status")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        if not args.output.exists():
            print(f"Observability evidence is missing: {args.output}")
            return 1
        stored = json.loads(args.output.read_text(encoding="utf-8"))
        stored_errors = validate_observability_evidence(stored)
        live = build_observability_evidence(iterations=args.iterations)
        live_errors = validate_observability_evidence(live)
        if stored_errors or live_errors:
            print(
                "Observability evidence failed: "
                f"stored={stored_errors or 'pass'} live={live_errors or 'pass'}"
            )
            return 1
        print(
            "Observability evidence passed: "
            f"stored_p95={stored['overhead']['per_span_p95_ms']}ms "
            f"live_p95={live['overhead']['per_span_p95_ms']}ms"
        )
        return 0

    evidence = build_observability_evidence(iterations=args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote observability evidence: {args.output}")
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
