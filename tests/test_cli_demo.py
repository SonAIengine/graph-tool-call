"""Public launch demo contract tests."""

from __future__ import annotations

import json
import subprocess
import sys

from graph_tool_call.demo import run_dependency_chain_demo


def test_dependency_chain_demo_uses_real_retrieval_and_contract_closure() -> None:
    result = run_dependency_chain_demo()

    assert result["target"] == "refundOrder"
    assert result["required_producers"] == ["findOrdersByEmail"]
    assert result["execution_order"] == ["findOrdersByEmail", "refundOrder"]
    assert result["closure_status"] == "ready"
    assert result["dependency_evidence"][0]["field_key"] == "order_id"
    assert "api_contract" in result["dependency_evidence"][0]["sources"]
    assert "openapi_link" in result["dependency_evidence"][0]["sources"]
    assert result["context"]["estimated_reduction"] > 0.5


def test_dependency_chain_demo_cli_text_and_json_match() -> None:
    text_result = subprocess.run(
        [sys.executable, "-m", "graph_tool_call", "demo", "dependency-chain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Selected target:\n  refundOrder(order_id)" in text_result.stdout
    assert "1. findOrdersByEmail\n  2. refundOrder" in text_result.stdout

    json_result = subprocess.run(
        [sys.executable, "-m", "graph_tool_call", "demo", "dependency-chain", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(json_result.stdout)
    assert payload["execution_order"] == ["findOrdersByEmail", "refundOrder"]
