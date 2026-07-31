"""Contract tests for the paired B6b/B6c paper model loop."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.experiment.artifact import ExperimentArtifact, finalize_artifact, write_artifact
from benchmarks.paper_model_loop.catalog import (
    B6B_BASELINE,
    B6C_BASELINE,
    build_selection_catalog,
    hydrate_full_schemas,
    validate_paired_case_contract,
    validate_plan_payload,
)
from benchmarks.paper_model_loop.client import ModelResponse, redacted_url
from benchmarks.paper_model_loop.run import run_paired_model_loop
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


class _CatalogAwareModel:
    provider = "injected"

    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []
        self._decision: dict[str, Any] = {}

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
        if "Frozen tool catalog:" in user:
            catalog = json.loads(user.split("Frozen tool catalog:\n", 1)[1])
            names = [str(tool["name"]) for tool in catalog]
            target = "placeOrder" if "placeOrder" in names else names[-1]
            self._decision = {
                "target_tool": target,
                "supporting_tools": [name for name in names if name != target],
            }
            return ModelResponse(
                content=json.dumps(self._decision),
                input_tokens=100,
                output_tokens=12,
                latency_ms=5.0,
                status_code=200,
            )

        schemas_text = user.split("Hydrated complete schemas:\n", 1)[1].split(
            "\n\nRequired output shape:",
            1,
        )[0]
        schemas = json.loads(schemas_text)
        plan = []
        for schema in schemas:
            required = [
                parameter["name"]
                for parameter in schema.get("parameters") or []
                if parameter.get("required")
            ]
            plan.append(
                {
                    "tool": schema["name"],
                    "arguments": {},
                    "bindings": {},
                    "missing_required_inputs": required,
                }
            )
        return ModelResponse(
            content=json.dumps(
                {
                    "final_target": self._decision["target_tool"],
                    "plan": plan,
                }
            ),
            input_tokens=200,
            output_tokens=30,
            latency_ms=8.0,
            status_code=200,
        )


def test_paired_contract_requires_identical_ranking_and_admission_evidence() -> None:
    case = _paired_case()
    contract = validate_paired_case_contract(case)

    assert contract["ranking_identical"] is True
    assert contract["projected_names"] == ["target"]

    changed = copy.deepcopy(case)
    changed["observed"][B6C_BASELINE]["retrieved"].reverse()
    with pytest.raises(ValueError, match="same frozen ranking"):
        validate_paired_case_contract(changed)

    unsupported = copy.deepcopy(case)
    unsupported["token_budget_observed"][B6C_BASELINE]["schema_modes"]["producer"] = (
        "contract_projected"
    )
    with pytest.raises(ValueError, match="admission evidence"):
        validate_paired_case_contract(unsupported)


def test_selection_projection_is_replaced_by_complete_hydrated_schema() -> None:
    tools = {
        "producer": ToolSchema(
            name="producer",
            description="Produce an identifier.",
            parameters=[ToolParameter(name="query", required=False)],
        ),
        "target": ToolSchema(
            name="target",
            description="Use the identifier.",
            parameters=[
                ToolParameter(name="identifier", required=True),
                ToolParameter(name="verbose", type="boolean", required=False),
            ],
            metadata={"ai_metadata": {"one_line_summary": "Use one identifier."}},
        ),
    }
    case = _paired_case()
    catalog = build_selection_catalog(
        case,
        tools,
        baseline=B6C_BASELINE,
        token_counter=_CharCounter(),
    )

    projected = catalog.payloads[1]
    assert projected["name"] == "target"
    assert [parameter["name"] for parameter in projected["parameters"]] == ["identifier"]
    assert catalog.schema_modes["target"] == "contract_projected"

    hydrated = hydrate_full_schemas(catalog.selected_names, tools)
    full_target = hydrated.payloads[1]
    assert [parameter["name"] for parameter in full_target["parameters"]] == [
        "identifier",
        "verbose",
    ]
    assert hydrated.success is True
    assert hydrated.source_schema_sha256["target"]
    assert (
        hydrated.schema_sha256["target"]
        != hashlib.sha256(json.dumps(projected, sort_keys=True).encode()).hexdigest()
    )

    over_budget = copy.deepcopy(case)
    over_budget["token_budget_observed"][B6C_BASELINE]["token_budget_limit"] = (
        catalog.schema_tokens - 1
    )
    with pytest.raises(ValueError, match="exceeds"):
        build_selection_catalog(
            over_budget,
            tools,
            baseline=B6C_BASELINE,
            token_counter=_CharCounter(),
        )


def test_plan_validation_requires_known_tools_arguments_and_required_accounting() -> None:
    tools = {
        "listItems": ToolSchema(
            name="listItems",
            metadata={
                "api_contract": {
                    "produces": [
                        {
                            "field_name": "itemId",
                            "json_path": "$.items[*].itemId",
                            "field_type": "integer",
                        }
                    ]
                }
            },
        ),
        "readItem": ToolSchema(
            name="readItem",
            parameters=[
                ToolParameter(name="itemId", type="integer", required=True),
                ToolParameter(name="verbose", type="boolean", required=False),
            ],
        ),
    }
    hydrated = hydrate_full_schemas(["listItems", "readItem"], tools)
    valid = validate_plan_payload(
        {
            "final_target": "readItem",
            "plan": [
                {
                    "tool": "listItems",
                    "arguments": {},
                    "bindings": {},
                    "missing_required_inputs": [],
                },
                {
                    "tool": "readItem",
                    "arguments": {"verbose": True},
                    "bindings": {
                        "itemId": {
                            "from_tool": "listItems",
                            "path": "$.items[*].itemId",
                        }
                    },
                    "missing_required_inputs": [],
                },
            ],
        },
        selected_target="readItem",
        hydrated=hydrated,
        tools_by_name=tools,
    )
    assert valid.valid is True

    invalid = validate_plan_payload(
        {
            "final_target": "readItem",
            "plan": [
                {
                    "tool": "readItem",
                    "arguments": {"unknown": "value", "itemId": "not-an-int"},
                    "missing_required_inputs": ["invented"],
                }
            ],
        },
        selected_target="readItem",
        hydrated=hydrated,
        tools_by_name=tools,
    )
    assert invalid.valid is False
    assert {
        "plan_unknown_argument",
        "plan_argument_type_invalid",
        "plan_missing_input_invalid",
    }.issubset(invalid.reason_codes)

    invalid_path = validate_plan_payload(
        {
            "final_target": "readItem",
            "plan": [
                {
                    "tool": "listItems",
                    "arguments": {},
                    "missing_required_inputs": [],
                },
                {
                    "tool": "readItem",
                    "bindings": {
                        "itemId": {
                            "from_tool": "listItems",
                            "path": "$.items[*].missing",
                        }
                    },
                    "missing_required_inputs": [],
                },
            ],
        },
        selected_target="readItem",
        hydrated=hydrated,
        tools_by_name=tools,
    )
    assert "plan_binding_path_invalid" in invalid_path.reason_codes


def test_paired_model_loop_records_b6c_gain_and_valid_hydration(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    write_artifact(baseline_path, _baseline_artifact())
    client = _CatalogAwareModel()

    artifact = run_paired_model_loop(
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

    paired = artifact.summary["paired_b6c_minus_b6b"]
    assert paired["selector_target_accuracy"]["mean_before"] == 0.0
    assert paired["selector_target_accuracy"]["mean_after"] == 1.0
    assert paired["all_required_selected"]["mean_after"] == 1.0
    assert paired["end_to_end_valid"]["mean_after"] == 1.0
    assert artifact.summary["protocol_integrity"] == {
        "paired_case_count": 1,
        "ranking_identity_rate": 1.0,
        "catalog_budget_compliance_rate": 1.0,
    }
    b6c = next(case for case in artifact.cases if case["context"]["baseline"] == B6C_BASELINE)
    assert b6c["observed"]["hydration"]["success"] is True
    assert b6c["observed"]["selection_catalog"]["schema_modes"]["placeOrder"] == (
        "contract_projected"
    )
    assert b6c["failure"]["reason_codes"] == []
    all_prompt_text = "\n".join(
        message["content"] for messages in client.messages for message in messages
    )
    assert "expected_targets" not in all_prompt_text
    assert "required_producers" not in all_prompt_text
    assert "source_schema_sha256" in all_prompt_text
    assert "api_contract" in all_prompt_text


def test_redacted_url_removes_embedded_credentials() -> None:
    assert redacted_url("https://user:secret@example.com/v1") == "https://***@example.com/v1"


def _paired_case() -> dict[str, Any]:
    ranking = ["producer", "target"]
    return {
        "case_id": "fixture-case",
        "query": "Use a produced identifier.",
        "context": {
            "source_id": "fixture-source",
            "family_id": "fixture-family",
            "split": "dev",
        },
        "expected": {
            "expected_targets": ["target"],
            "required_producers": ["producer"],
            "acceptable_alternatives": [],
        },
        "observed": {
            B6B_BASELINE: {
                "retrieved": ranking,
                "diagnostics": {
                    "candidate_admission": {
                        "admitted": [{"name": "target"}],
                    }
                },
            },
            B6C_BASELINE: {"retrieved": list(ranking)},
        },
        "token_budget_observed": {
            B6B_BASELINE: {
                "retrieved": ["producer"],
                "schema_modes": {"producer": "full"},
                "schema_tokens": 0,
                "token_budget_limit": 10000,
            },
            B6C_BASELINE: {
                "retrieved": ranking,
                "schema_modes": {
                    "producer": "full",
                    "target": "contract_projected",
                },
                "schema_tokens": 0,
                "token_budget_limit": 10000,
            },
        },
    }


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
                "limit": 100000,
            },
        },
        provenance=dict(PROVENANCE),
        tokenizer={
            "name": "fixture-tokenizer",
            "revision": "fixture-revision",
        },
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
                            "candidate_admission": {
                                "admitted": [{"name": "placeOrder"}],
                            }
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
                        "token_budget_limit": 100000,
                    },
                    B6C_BASELINE: {
                        "retrieved": ranking,
                        "schema_modes": {
                            "findPetsByStatus": "full",
                            "getPetById": "full",
                            "placeOrder": "contract_projected",
                        },
                        "schema_tokens": 0,
                        "token_budget_limit": 100000,
                    },
                },
            }
        ],
        source={
            "type": "fixture",
            "sha256": "c" * 64,
        },
    )
    return finalize_artifact(artifact)
