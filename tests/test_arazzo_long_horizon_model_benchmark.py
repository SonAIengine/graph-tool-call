from __future__ import annotations

import re

import benchmarks.paper_model_loop.client as client_module
from benchmarks.arazzo_long_horizon.model_run import _provider_options, run_model_benchmark
from benchmarks.paper_model_loop import HTTPModelClient, ModelResponse


class ExactTargetClient:
    provider = "test"

    def complete(self, messages, *, seed, timeout, max_tokens):
        query = messages[-1]["content"]
        if "공급업체" in query:
            target = "issueSupplierActivationCertificate"
        elif "장애 복구" in query:
            target = "issueIncidentRecoveryReport"
        else:
            target = "issuePublicationApprovalCertificate"
        assert re.search(rf'"name":"{target}"', query)
        return ModelResponse(
            content=f'{{"target_tool":"{target}","supporting_tools":[]}}',
            input_tokens=100,
            output_tokens=12,
            latency_ms=5.0,
            status_code=200,
            finish_reason="stop",
        )


def test_model_gate_separates_llm_selection_from_graph_execution():
    report = run_model_benchmark(
        model="fixture-model",
        model_revision="test",
        llm_url="https://user:secret@example.invalid/v1",
        catalog_size=60,
        workflow_lengths=(3, 10, 30),
        model_client=ExactTargetClient(),
    )

    assert report["summary"]["status"] == "pass"
    assert report["summary"]["metrics"]["llm_target_exact"] == 1.0
    assert report["summary"]["metrics"]["goal_completion_rate"] == 1.0
    assert [case["executed_call_count"] for case in report["cases"]] == [3, 10, 30]
    assert report["model"]["endpoint"] == "https://***@example.invalid/v1"
    assert report["summary"]["usage"] == {"input_tokens": 300, "output_tokens": 36}


class HallucinatingClient:
    provider = "test"

    def complete(self, messages, *, seed, timeout, max_tokens):
        return ModelResponse(content='{"target_tool":"notInCatalog"}', status_code=200)


def test_model_gate_records_hallucination_without_confusing_it_with_retrieval():
    report = run_model_benchmark(
        model="fixture-model",
        model_revision="test",
        llm_url="https://example.invalid/v1",
        catalog_size=40,
        workflow_lengths=(3,),
        model_client=HallucinatingClient(),
    )
    case = report["cases"][0]

    assert case["target_hit_at_k"] == 1.0
    assert case["llm_target_exact"] == 0.0
    assert case["llm_target_in_catalog"] == 0.0
    assert "selector_tool_not_in_catalog" in case["model_reason_codes"]
    assert report["summary"]["status"] == "fail"


def test_deepseek_provider_options_disable_thinking_and_require_json():
    assert _provider_options("deepseek") == {
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    assert _provider_options("default") == {}


def test_http_model_client_forwards_provider_options(monkeypatch):
    captured = {}

    def fake_post(url, payload, *, headers, timeout):
        captured.update({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        return (
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {},
            },
            200,
            "",
        )

    monkeypatch.setattr(client_module, "_post_json", fake_post)
    client = HTTPModelClient(
        model="deepseek-v4-flash",
        url="https://api.deepseek.com/v1",
        provider="openai-compatible",
        extra_body=_provider_options("deepseek"),
    )

    response = client.complete(
        [{"role": "user", "content": "select"}],
        seed=17,
        timeout=30,
        max_tokens=64,
    )

    assert response.status_code == 200
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "chat_template_kwargs" not in captured["payload"]
