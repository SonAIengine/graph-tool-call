"""Tests for the unified paper experiment artifact."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

from benchmarks.experiment.adapters import adapt_legacy_report
from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    compute_artifact_id,
    compute_run_id,
    finalize_artifact,
    load_artifact,
    validate_artifact,
    write_artifact,
)
from benchmarks.reporter import BenchmarkReport, DatasetResult, QueryResult

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


def test_experiment_artifact_round_trip_and_ids_are_deterministic(tmp_path: Path) -> None:
    artifact = _artifact()
    finalize_artifact(artifact)
    first_run_id = artifact.run_id
    first_artifact_id = artifact.artifact_id

    clone = ExperimentArtifact.from_dict(artifact.to_dict())
    finalize_artifact(clone)

    assert clone.run_id == first_run_id
    assert clone.artifact_id == first_artifact_id
    assert validate_artifact(clone).valid is True

    path = write_artifact(tmp_path / "artifact.json", clone)
    loaded = load_artifact(path)
    assert loaded.to_dict() == clone.to_dict()


def test_result_change_preserves_run_id_but_changes_artifact_id() -> None:
    artifact = finalize_artifact(_artifact())
    changed = ExperimentArtifact.from_dict(copy.deepcopy(artifact.to_dict()))
    changed.cases[0]["metrics"]["recall_at_k"] = 0.0
    changed.run_id = compute_run_id(changed)
    changed.artifact_id = compute_artifact_id(changed)

    assert changed.run_id == artifact.run_id
    assert changed.artifact_id != artifact.artifact_id
    assert validate_artifact(changed).valid is True


def test_validation_detects_content_tampering() -> None:
    artifact = finalize_artifact(_artifact())
    artifact.summary["recall_at_k"] = 0.5

    report = validate_artifact(artifact)

    assert report.valid is False
    assert "experiment_artifact_id_mismatch" in _issue_codes(report)


def test_validation_requires_dataset_source_and_replay_provenance() -> None:
    artifact = _artifact()
    artifact.dataset = {"id": "fixture-v1", "split": "dev"}
    artifact.source = {}
    artifact.replay = {"command": [], "working_directory": "."}
    finalize_artifact(artifact)

    report = validate_artifact(artifact)

    assert report.valid is False
    assert {
        "experiment_dataset_fingerprint_missing",
        "experiment_replay_command_missing",
        "experiment_source_sha256_missing",
        "experiment_source_type_missing",
    }.issubset(_issue_codes(report))


def test_model_run_requires_provider_and_revision() -> None:
    artifact = _artifact()
    artifact.run_kind = "model"
    artifact.model = {"name": "qwen"}
    finalize_artifact(artifact)

    report = validate_artifact(artifact)

    assert report.valid is False
    assert {
        "experiment_model_provider_missing",
        "experiment_model_revision_missing",
    }.issubset(_issue_codes(report))


def test_reporter_adapter_preserves_cases_and_common_metrics() -> None:
    report = BenchmarkReport(
        timestamp="2026-07-28T00:00:00+00:00",
        mode="retrieval_only",
        top_k=5,
        datasets=[
            DatasetResult(
                name="petstore",
                tool_count=19,
                query_count=1,
                avg_recall_at_k=1.0,
                queries=[
                    QueryResult(
                        query="Find an available pet.",
                        expected_tools=["findPetsByStatus"],
                        retrieved_tools=["findPetsByStatus"],
                        recall_at_k=1.0,
                        mrr=1.0,
                    )
                ],
            )
        ],
    )

    artifact = adapt_legacy_report(
        report,
        source_type="reporter",
        dataset={"id": "petstore", "split": "train"},
        replay_command=["python", "-m", "benchmarks.run_benchmark", "--dataset", "petstore"],
    )

    assert validate_artifact(artifact).valid is True
    assert len(artifact.cases) == 1
    assert artifact.cases[0]["expected"]["expected_tools"] == ["findPetsByStatus"]
    assert artifact.cases[0]["observed"]["retrieved_tools"] == ["findPetsByStatus"]
    assert artifact.cases[0]["metrics"]["recall_at_k"] == 1.0
    assert artifact.source["adapter_non_destructive"] is True
    assert artifact.source["legacy_report_embedded"] is False


def test_bfcl_adapter_normalizes_nested_category_cases() -> None:
    report = {
        "benchmark": "BFCL v4 Tool Selection",
        "methodology": "bfcl_function_call_tool_selection",
        "model": "none",
        "top_k": 5,
        "categories": [
            {
                "category": "simple_python",
                "cases": [
                    {
                        "case_id": "case-1",
                        "query": "Get weather.",
                        "expected_tools": ["weather"],
                        "retrieved": ["weather"],
                        "recall_at_5": 1.0,
                        "mrr": 1.0,
                    }
                ],
            }
        ],
        "summary": {"recall_at_5": 1.0},
    }

    artifact = adapt_legacy_report(
        report,
        source_type="bfcl_tool_selection",
        dataset={"id": "bfcl-v4-subset", "split": "dev"},
    )

    assert validate_artifact(artifact).valid is True
    assert artifact.run_kind == "deterministic"
    assert artifact.cases[0]["context"]["category"] == "simple_python"
    assert artifact.cases[0]["metrics"]["recall_at_5"] == 1.0


def test_xgen_tool_graph_adapter_disambiguates_pipeline_case_ids() -> None:
    report = {
        "benchmark": "XGEN Tool Graph",
        "methodology": "deterministic_engine_contract",
        "model": "none",
        "pipelines": [
            {
                "name": "keyword",
                "cases": [
                    {
                        "case_id": "goods-detail",
                        "query": "상품 상세",
                        "expected_target": "getGoodsDetail",
                        "retrieved": ["getGoodsDetail"],
                        "target_recall_at_k": 1.0,
                    }
                ],
            },
            {
                "name": "graph",
                "cases": [
                    {
                        "case_id": "goods-detail",
                        "query": "상품 상세",
                        "expected_target": "getGoodsDetail",
                        "retrieved": ["getGoodsDetail"],
                        "target_recall_at_k": 1.0,
                    }
                ],
            },
        ],
    }

    artifact = adapt_legacy_report(
        report,
        source_type="xgen_tool_graph",
        dataset={"id": "xgen-tool-graph", "split": "dev"},
    )

    assert validate_artifact(artifact).valid is True
    assert [case["case_id"] for case in artifact.cases] == [
        "goods-detail",
        "goods-detail::2",
    ]
    assert [case["context"]["pipeline"] for case in artifact.cases] == ["keyword", "graph"]


def test_artifact_is_plain_json() -> None:
    artifact = finalize_artifact(_artifact())

    encoded = json.dumps(asdict(artifact), ensure_ascii=False, sort_keys=True)

    assert artifact.artifact_id in encoded


def _artifact() -> ExperimentArtifact:
    return ExperimentArtifact(
        benchmark="unit",
        methodology="deterministic_retrieval",
        run_kind="deterministic",
        created_at="2026-07-28T00:00:00+00:00",
        seed=17,
        dataset={
            "id": "fixture-v1",
            "split": "dev",
            "manifest_sha256": "c" * 64,
        },
        config={"top_k": 5},
        provenance=dict(PROVENANCE),
        tokenizer={"name": "test-tokenizer", "revision": "revision-1"},
        replay={"command": ["python", "-m", "benchmarks.fixture"], "working_directory": "."},
        summary={"recall_at_k": 1.0},
        statistics={"confidence_interval": [1.0, 1.0]},
        cases=[
            {
                "case_id": "case-1",
                "query": "find the tool",
                "context": {},
                "expected": {"expected_tools": ["tool"]},
                "observed": {"retrieved": ["tool"]},
                "metrics": {"recall_at_k": 1.0},
                "stages": {},
                "failure": {},
            }
        ],
        source={"type": "fixture", "sha256": "d" * 64},
    )


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}
