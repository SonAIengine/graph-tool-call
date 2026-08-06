from __future__ import annotations

import json
import time

import pytest

from graph_tool_call import TraceEnvelope, TraceRecorder, replay_trace
from graph_tool_call.observability import (
    OpenTelemetryTraceExporter,
    record_dependency_closure,
    record_plan,
    record_retrieval_result,
    record_runner_events,
    record_selector_result,
    record_tool_bundle,
)


def test_trace_round_trip_scrubs_secrets_and_replays_decisions(tmp_path):
    recorder = TraceRecorder(
        "tool_selection",
        trace_id="trace-test-1",
        attributes={
            "query": "Find account for son@example.com",
            "Authorization": "Bearer top-secret-token",
        },
    )
    with recorder.start_span("retrieval", attributes={"cookie": "session=secret"}) as span:
        span.decision(
            "getAccount",
            "ranked",
            ["retrieval.seed_match"],
            score=0.9,
            rank_after=1,
            evidence={"request_body": {"password": "secret"}},
        )

    path = recorder.write(tmp_path / "trace.json")
    raw = path.read_text(encoding="utf-8")
    assert "top-secret-token" not in raw
    assert "son@example.com" not in raw
    assert '"Authorization": "[REDACTED]"' in raw

    loaded = TraceEnvelope.from_dict(json.loads(raw))
    replay = replay_trace(loaded)
    assert replay["trace_id"] == "trace-test-1"
    assert replay["stage_order"] == ["retrieval"]
    assert replay["reason_coverage"] == 1.0
    assert replay["outcomes"] == {"ranked": ["getAccount"]}


def test_w3c_hex_trace_id_is_preserved_for_correlation():
    trace_id = "0123456789abcdef0123456789abcdef"
    recorder = TraceRecorder("retrieve", trace_id=trace_id)

    replay = replay_trace(recorder.finish().to_dict())

    assert replay["trace_id"] == trace_id


def test_structural_names_are_scrubbed_without_losing_trace_correlation():
    recorder = TraceRecorder("Bearer operation-secret", trace_id="trace-safe-names")
    with recorder.start_span("runner", "Bearer span-secret") as span:
        span.decision("Bearer subject-secret", "ranked", ["retrieval.rank_score"])
        span.event("Bearer event-secret")

    payload = json.dumps(recorder.to_dict())

    assert "operation-secret" not in payload
    assert "span-secret" not in payload
    assert "subject-secret" not in payload
    assert "event-secret" not in payload
    assert "trace-safe-names" in payload


def test_stage_adapters_explain_every_candidate_and_admission_decision():
    recorder = TraceRecorder("search_plan", trace_id="trace-test-2")
    with recorder.start_span("retrieval") as span:
        record_retrieval_result(
            span,
            {
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
                "stats": {"seeds": ["getOrder"], "visited_nodes": 2, "visited_edges": 1},
            },
        )
    with recorder.start_span("target_selection") as span:
        record_selector_result(
            span,
            {
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
        )
    with recorder.start_span("dependency_closure") as span:
        record_dependency_closure(
            span,
            {
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
        )
    with recorder.start_span("schema_admission") as span:
        record_tool_bundle(
            span,
            {
                "target": "getOrder",
                "required_tools": ["listOrders"],
                "optional_tools": ["searchCustomers"],
                "admitted_tools": ["getOrder", "listOrders"],
                "omitted_tools": ["searchCustomers"],
                "token_budget": {"limit": 256, "used": 230},
                "closure_status": "ready",
            },
        )

    replay = replay_trace(recorder.finish())
    assert replay["reason_coverage"] == 1.0
    assert replay["outcomes"]["selected"] == ["getOrder"]
    assert replay["outcomes"]["expanded"] == ["listOrders"]
    assert replay["outcomes"]["omitted"] == ["searchCustomers"]
    assert all(decision["reason_codes"] for decision in replay["decisions"])


def test_plan_and_runner_adapters_do_not_persist_raw_arguments():
    recorder = TraceRecorder("plan_run", trace_id="trace-test-3")
    with recorder.start_span("plan") as span:
        record_plan(
            span,
            {
                "id": "plan-1",
                "steps": [
                    {
                        "id": "step-1",
                        "tool": "getUser",
                        "args": {"Authorization": "Bearer secret"},
                    }
                ],
            },
        )
    with recorder.start_span("runner") as span:
        record_runner_events(
            span,
            [
                {
                    "type": "step.completed",
                    "tool": "getUser",
                    "args_resolved": {"api_key": "secret"},
                    "output": {"email": "son@example.com"},
                }
            ],
        )
    payload = json.dumps(recorder.to_dict(), ensure_ascii=False)
    assert "Bearer secret" not in payload
    assert "son@example.com" not in payload
    assert '"planned"' in payload


def test_trace_recorder_adds_less_than_five_ms_per_simple_span():
    count = 200
    started = time.perf_counter()
    recorder = TraceRecorder("overhead", trace_id="trace-overhead")
    for index in range(count):
        with recorder.start_span("retrieval") as span:
            span.decision(f"tool-{index}", "ranked", ["retrieval.rank_score"])
    recorder.finish()
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms / count < 5.0


def test_otel_exporter_maps_trace_to_root_and_stage_spans():
    pytest.importorskip("opentelemetry")

    class FakeSpan:
        def __init__(self, name):
            self.name = name
            self.events = []
            self.status = None
            self.ended = False

        def add_event(self, name, attributes=None, timestamp=None):
            self.events.append((name, attributes, timestamp))

        def set_status(self, status):
            self.status = status

        def end(self, end_time=None):
            self.ended = True

    class FakeTracer:
        def __init__(self):
            self.spans = []

        def start_span(self, name, **kwargs):
            span = FakeSpan(name)
            self.spans.append(span)
            return span

    recorder = TraceRecorder("retrieve", trace_id="trace-otel")
    with recorder.start_span("retrieval", "retrieve_graphify") as span:
        span.decision("getOrder", "ranked", ["retrieval.seed_match"])
    tracer = FakeTracer()

    OpenTelemetryTraceExporter(tracer).export(recorder.finish())

    assert [span.name for span in tracer.spans] == [
        "graph-tool-call.retrieve",
        "retrieve_graphify",
    ]
    assert tracer.spans[1].events[0][0] == "graph_tool_call.decision"
    assert all(span.ended for span in tracer.spans)
