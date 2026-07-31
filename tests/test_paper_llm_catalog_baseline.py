"""Contract tests for the budgeted LLM-only catalog baseline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from benchmarks.experiment.artifact import ExperimentArtifact, finalize_artifact, write_artifact
from benchmarks.paper_model_loop.catalog import B6B_BASELINE, B6C_BASELINE
from benchmarks.paper_model_loop.client import ModelResponse
from benchmarks.paper_model_loop.llm_catalog_baseline import (
    B0L_BASELINE,
    build_llm_catalog_chunks,
    build_llm_catalog_index,
    parse_shortlist_decision,
)
from benchmarks.paper_model_loop.llm_catalog_run import (
    _hierarchical_select,
    _pair_cases,
    _validate_b6c_budget_identity,
    run_budgeted_llm_catalog_baseline,
)
from graph_tool_call.core.tool import ToolParameter, ToolSchema

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "benchmarks" / "corpus" / "manifest.json"
PROVENANCE = {
    "graph_tool_call_version": "0.test",
    "git_commit": "a" * 40,
    "git_dirty": False,
    "python_version": "3.12.0",
    "python_implementation": "CPython",
    "platform": "test",
    "dependency_lock_path": "poetry.lock",
    "dependency_lock_sha256": "b" * 64,
}


class _CharCounter:
    def count(self, text: str) -> int:
        return len(text)


class _HierarchicalFixtureModel:
    provider = "injected"

    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []
        self._target = ""

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        seed: int,
        timeout: int,
        max_tokens: int,
    ) -> ModelResponse:
        del seed, timeout, max_tokens
        self.messages.append(messages)
        user = messages[-1]["content"]
        if "Catalog chunk:" in user:
            catalog = json.loads(user.split("Catalog chunk:\n", 1)[1])
            names = [str(tool["name"]) for tool in catalog]
            match = re.search(r"at most (\d+) names", messages[0]["content"])
            limit = int(match.group(1)) if match else 1
            candidates = ["targetTool"] if "targetTool" in names else []
            candidates.extend(name for name in names if name not in candidates)
            return _response({"candidate_tools": list(dict.fromkeys(candidates))[:limit]})
        if "Frozen tool catalog:" in user:
            catalog = json.loads(user.split("Frozen tool catalog:\n", 1)[1])
            names = [str(tool["name"]) for tool in catalog]
            self._target = "placeOrder" if "placeOrder" in names else "targetTool"
            if self._target not in names:
                self._target = names[-1]
            supports = [name for name in names if name != self._target][:2]
            return _response(
                {"target_tool": self._target, "supporting_tools": supports},
                input_tokens=100,
            )

        schemas_text = user.split("Hydrated complete schemas:\n", 1)[1].split(
            "\n\nRequired output shape:", 1
        )[0]
        schemas = json.loads(schemas_text)
        plan = [
            {
                "tool": schema["name"],
                "arguments": {},
                "bindings": {},
                "missing_required_inputs": [
                    parameter["name"]
                    for parameter in schema.get("parameters") or []
                    if parameter.get("required")
                ],
            }
            for schema in schemas
        ]
        return _response(
            {"final_target": self._target, "plan": plan},
            input_tokens=200,
        )


def test_catalog_index_and_chunks_are_deterministic_and_budget_compliant() -> None:
    tools = {
        f"tool{index}": ToolSchema(
            name=f"tool{index}",
            description="Inspect one resource with a bounded catalog description.",
            parameters=[ToolParameter(name="resourceId", required=index % 2 == 0)],
            metadata={
                "method": "GET",
                "path": f"/resources/{index}",
                "api_contract": {
                    "produces": [{"field_name": "resourceId", "field_type": "string"}]
                },
            },
        )
        for index in reversed(range(8))
    }
    entries = build_llm_catalog_index(tools)
    chunks = build_llm_catalog_chunks(
        entries,
        token_counter=_CharCounter(),
        token_budget=700,
        round_index=0,
    )

    assert [entry["name"] for entry in entries] == [f"tool{index}" for index in range(8)]
    assert len(chunks) > 1
    assert [name for chunk in chunks for name in chunk.names] == [
        f"tool{index}" for index in range(8)
    ]
    assert all(chunk.catalog_tokens <= 700 for chunk in chunks)
    assert chunks == build_llm_catalog_chunks(
        entries,
        token_counter=_CharCounter(),
        token_budget=700,
        round_index=0,
    )


def test_shortlist_parser_caps_output_and_hierarchical_selector_covers_catalog() -> None:
    parsed = parse_shortlist_decision(
        json.dumps({"candidate_tools": ["a", "b", "c", "d"]}),
        shortlist_size=3,
    )
    assert parsed.candidate_tools == ["a", "b", "c"]
    assert parsed.reason_codes == ["shortlist_limit_exceeded"]

    tools = {
        **{
            f"tool{index}": ToolSchema(
                name=f"tool{index}",
                description="Read one resource from a deliberately broad catalog.",
            )
            for index in range(10)
        },
        "targetTool": ToolSchema(name="targetTool", description="Final requested operation."),
    }
    result = _hierarchical_select(
        "Run the final requested operation.",
        tools,
        paired_seed=17,
        token_counter=_CharCounter(),
        catalog_token_budget=1_000,
        model_client=_HierarchicalFixtureModel(),
        timeout=10,
        max_selection_tokens=100,
        shortlist_size=2,
        max_hierarchy_rounds=8,
        max_selected_tools=3,
        selector_concurrency=2,
    )

    assert result["decision"].target_tool == "targetTool"
    assert result["initial_catalog_coverage_rate"] == 1.0
    assert result["model_call_count"] > 1
    assert result["max_chunk_tokens"] <= 1_000
    assert result["catalog_tokens_scanned"] > result["max_chunk_tokens"]
    assert result["wall_latency_ms"] > 0
    assert result["model_latency_sum_ms"] > 0
    assert not any(code.startswith("hierarchy_") for code in result["failure_codes"])
    local_rounds = [row for row in result["trace"]["rounds"] if row["mode"] == "local_shortlist"]
    assert all(row["output_candidate_count"] < row["input_candidate_count"] for row in local_rounds)


def test_b0l_runner_pairs_same_budget_with_b6c_and_records_cost(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    write_artifact(baseline_path, _baseline_artifact())
    client = _HierarchicalFixtureModel()

    artifact = run_budgeted_llm_catalog_baseline(
        baseline_path,
        manifest_path=MANIFEST_PATH,
        model="fixture-model",
        model_revision="fixture-revision",
        provider="injected",
        llm_url="injected://fixture",
        repeats=1,
        bootstrap_resamples=20,
        model_client=client,
        token_counter=_CharCounter(),
        created_at="2026-07-31T00:00:00+00:00",
    )

    assert artifact.config["catalog_token_budget_per_call"] == 100_000
    assert artifact.config["ground_truth_in_prompt"] is False
    assert artifact.config["graph_edges_used_by_b0_l"] is False
    assert artifact.config["catalog_final_selection_revision"] == ("paper-b0l-final-selection-v1")
    assert artifact.summary["protocol_integrity"] == {
        "paired_case_count": 1,
        "original_case_cluster_count": 1,
        "repeat_count": 1,
        "complete_repeat_grid_rate": 1.0,
        "catalog_budget_compliance_rate": 1.0,
        "b0_l_initial_catalog_coverage_rate": 1.0,
    }
    assert set(artifact.summary["baselines"]) == {B6C_BASELINE, B0L_BASELINE}
    assert (
        artifact.statistics["clustered_paired_bootstrap"]["end_to_end_valid"]["cluster_count"] == 1
    )
    b0l = next(case for case in artifact.cases if case["context"]["baseline"] == B0L_BASELINE)
    assert b0l["metrics"]["catalog_tool_coverage_rate"] == 1.0
    assert b0l["metrics"]["selection_model_call_count"] >= 1
    assert b0l["observed"]["selection_catalog"]["total_tool_count"] == 19
    prompt = "\n".join(message["content"] for messages in client.messages for message in messages)
    assert "expected_targets" not in prompt
    assert "required_producers" not in prompt


def test_comparison_rejects_budget_and_pair_identity_mismatch() -> None:
    artifact = _baseline_artifact()
    _validate_b6c_budget_identity(artifact.cases, 100_000)
    try:
        _validate_b6c_budget_identity(artifact.cases, 2_048)
    except ValueError as exc:
        assert "same frozen" in str(exc)
    else:
        raise AssertionError("Expected mismatched budgets to be rejected.")

    pair_key = "case-a::repeat-0"
    rows = [
        {
            "context": {
                "pair_key": pair_key,
                "baseline": baseline,
                "original_case_id": original_case_id,
                "repeat": 0,
            }
        }
        for baseline, original_case_id in (
            (B6C_BASELINE, "case-a"),
            (B0L_BASELINE, "case-b"),
        )
    ]
    try:
        _pair_cases(rows)
    except ValueError as exc:
        assert "identity mismatch" in str(exc)
    else:
        raise AssertionError("Expected mismatched pair identities to be rejected.")


def _response(
    payload: dict[str, Any],
    *,
    input_tokens: int = 50,
) -> ModelResponse:
    return ModelResponse(
        content=json.dumps(payload),
        input_tokens=input_tokens,
        output_tokens=10,
        latency_ms=2.0,
        status_code=200,
    )


def _baseline_artifact() -> ExperimentArtifact:
    manifest_sha = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    ranking = ["findPetsByStatus", "getPetById", "placeOrder"]
    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-tool-retrieval",
        methodology="paired-fixed-baselines-v8",
        run_kind="deterministic",
        created_at="2026-07-31T00:00:00+00:00",
        seed=17,
        dataset={
            "id": "fixture-paper-corpus",
            "split": "train",
            "splits": ["train"],
            "manifest_sha256": manifest_sha,
            "held_out_accessed": False,
        },
        config={
            "baselines": {
                B6B_BASELINE: {"label": "B6b"},
                B6C_BASELINE: {"label": "B6c"},
            },
            "token_budget": {
                "type": "model_facing_schema_tokens",
                "limit": 100_000,
            },
        },
        provenance=dict(PROVENANCE),
        tokenizer={"name": "fixture-tokenizer", "revision": "fixture-revision"},
        replay={"command": ["python", "-m", "fixture"], "working_directory": "."},
        cases=[
            {
                "case_id": "petstore-train-adoption-workflow",
                "query": "Find an available pet, inspect its details, and place an order.",
                "context": {
                    "source_id": "openapi-swagger-petstore-1.0.27",
                    "family_id": "swagger-petstore",
                    "split": "train",
                    "source_type": "openapi",
                },
                "expected": {
                    "expected_targets": ["placeOrder"],
                    "required_producers": ["findPetsByStatus", "getPetById"],
                    "acceptable_alternatives": [],
                },
                "observed": {
                    B6B_BASELINE: {
                        "retrieved": ranking,
                        "diagnostics": {
                            "candidate_admission": {"admitted": [{"name": "placeOrder"}]}
                        },
                    },
                    B6C_BASELINE: {"retrieved": list(ranking)},
                },
                "token_budget_observed": {
                    B6B_BASELINE: {
                        "retrieved": ranking[:2],
                        "schema_modes": {
                            "findPetsByStatus": "full",
                            "getPetById": "full",
                        },
                        "schema_tokens": 0,
                        "token_budget_limit": 100_000,
                    },
                    B6C_BASELINE: {
                        "retrieved": ranking,
                        "schema_modes": {
                            "findPetsByStatus": "full",
                            "getPetById": "full",
                            "placeOrder": "contract_projected",
                        },
                        "schema_tokens": 0,
                        "token_budget_limit": 100_000,
                    },
                },
            }
        ],
        source={"type": "fixture", "sha256": "c" * 64},
    )
    return finalize_artifact(artifact)
