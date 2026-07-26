"""Tests for the public heterogeneous paper-corpus manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchmarks.corpus import manifest as corpus_manifest


def test_seed_corpus_is_reproducible_but_not_claim_ready() -> None:
    report = corpus_manifest.validate_corpus_manifest(verify_ingest=True)

    assert report.integrity_ready is True
    assert report.paper_ready is False
    assert report.source_count == 3
    assert report.family_count == 3
    assert report.query_count == 17
    assert report.source_type_counts == {
        "graphql-introspection": 1,
        "mcp": 1,
        "openapi": 1,
    }
    assert report.split_query_counts == {"dev": 5, "test": 6, "train": 6}
    assert {profile["tool_count"] for profile in report.source_profiles} == {4, 11, 19}
    assert _issue_codes(report) == {"paper_source_family_coverage_insufficient"}


def test_corpus_manifest_detects_snapshot_tampering(tmp_path: Path) -> None:
    manifest_path, source_path = _write_minimal_corpus(tmp_path)
    source_path.write_text('{"tools": []}\n', encoding="utf-8")

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "snapshot_sha256_mismatch" in _issue_codes(report)


def test_corpus_manifest_rejects_api_family_split_leakage(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    duplicate = dict(document["sources"][0])
    duplicate["id"] = "mcp-seed-dev"
    duplicate["split"] = "dev"
    duplicate_ground_truth = tmp_path / "ground-truth-dev.json"
    ground_truth = json.loads((tmp_path / "ground-truth.json").read_text(encoding="utf-8"))
    ground_truth["dataset_id"] = "mcp-seed-dev"
    ground_truth["source_ids"] = ["mcp-seed-dev"]
    ground_truth["split"] = "dev"
    ground_truth["cases"][0]["case_id"] = "mcp-seed-dev-read"
    _write_json(duplicate_ground_truth, ground_truth)
    duplicate["ground_truth_path"] = duplicate_ground_truth.name
    duplicate["ground_truth_sha256"] = _sha256(duplicate_ground_truth)
    document["sources"].append(duplicate)
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "family_split_leakage" in _issue_codes(report)


def test_paper_core_source_requires_license_evidence(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["sources"][0]["license"] = {"spdx_id": "MIT"}
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "source_license_evidence_url_missing" in _issue_codes(report)


def test_corpus_manifest_rejects_artifact_path_escape(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    outside_path = tmp_path.parent / "outside-source.json"
    _write_json(outside_path, {"tools": []})
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["sources"][0]["snapshot_path"] = f"../{outside_path.name}"
    document["sources"][0]["sha256"] = _sha256(outside_path)
    document["sources"][0]["bytes"] = outside_path.stat().st_size
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "source_path_escape" in _issue_codes(report)


def test_corpus_manifest_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["sources"].append(dict(document["sources"][0]))
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "source_id_duplicate" in _issue_codes(report)


def test_ground_truth_cannot_reference_an_unknown_source(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    ground_truth_path = tmp_path / "ground-truth.json"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    ground_truth["source_ids"].append("unknown-source")
    _write_json(ground_truth_path, ground_truth)
    document["sources"][0]["ground_truth_sha256"] = _sha256(ground_truth_path)
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "ground_truth_unknown_source" in _issue_codes(report)


def test_hash_skip_cannot_establish_paper_readiness(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)

    report = corpus_manifest.validate_corpus_manifest(
        manifest_path,
        verify_hashes=False,
    )

    assert report.integrity_ready is True
    assert report.paper_ready is False
    assert "hash_verification_disabled" in _issue_codes(report)


def test_non_core_sources_cannot_satisfy_paper_policy(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["sources"][0]["paper_core"] = False
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is True
    assert report.paper_ready is False
    assert report.paper_core_source_count == 0
    assert report.paper_core_source_type_counts == {}
    assert report.paper_core_split_query_counts == {"dev": 0, "test": 0, "train": 0}
    assert {
        "paper_source_types_missing",
        "paper_splits_missing",
        "paper_source_family_coverage_insufficient",
        "paper_split_query_coverage_insufficient",
        "paper_non_core_sources_present",
    }.issubset(_issue_codes(report))


def test_paper_core_source_requires_audit_trail(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    del document["sources"][0]["audit"]
    _write_json(manifest_path, document)

    report = corpus_manifest.validate_corpus_manifest(manifest_path)

    assert report.integrity_ready is False
    assert "source_audit_missing" in _issue_codes(report)


def test_minimal_audited_corpus_can_satisfy_an_explicit_policy(tmp_path: Path) -> None:
    manifest_path, _source_path = _write_minimal_corpus(tmp_path)

    report = corpus_manifest.validate_corpus_manifest(manifest_path, verify_ingest=True)

    assert report.integrity_ready is True
    assert report.paper_ready is True
    assert report.source_profiles[0]["adapter"] == "mcp-tools"
    assert report.source_profiles[0]["tool_count"] == 1


def test_cli_distinguishes_integrity_from_paper_readiness(capsys: Any) -> None:
    integrity_exit = corpus_manifest.main(["--verify-ingest"])
    claim_exit = corpus_manifest.main(["--verify-ingest", "--require-paper-ready"])

    assert integrity_exit == 0
    assert claim_exit == 2
    output = capsys.readouterr().out
    assert "integrity=pass" in output
    assert "paper_ready=fail" in output


def _write_minimal_corpus(tmp_path: Path) -> tuple[Path, Path]:
    source_path = tmp_path / "source.json"
    ground_truth_path = tmp_path / "ground-truth.json"
    manifest_path = tmp_path / "manifest.json"
    _write_json(
        source_path,
        {
            "tools": [
                {
                    "name": "read_record",
                    "description": "Read one record.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                }
            ]
        },
    )
    _write_json(
        ground_truth_path,
        {
            "schema_version": 1,
            "dataset_id": "mcp-seed-train",
            "family_id": "mcp-seed",
            "source_ids": ["mcp-seed-train"],
            "split": "train",
            "languages": ["en"],
            "cases": [
                {
                    "case_id": "mcp-seed-train-read",
                    "query": "Read record 1.",
                    "expected_targets": ["read_record"],
                    "acceptable_alternatives": [],
                    "required_producers": [],
                    "provenance": {
                        "origin": "human-authored",
                        "annotator_version": "test-v1",
                    },
                }
            ],
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": 1,
            "corpus_id": "minimal-test-corpus",
            "repository_root": ".",
            "paper_readiness_policy": {
                "required_source_types": ["mcp"],
                "required_splits": ["train"],
                "min_families_per_source_type": 1,
                "min_queries_per_split": 1,
            },
            "sources": [
                {
                    "id": "mcp-seed-train",
                    "family_id": "mcp-seed",
                    "source_type": "mcp",
                    "adapter": "mcp-tools",
                    "domain": "test",
                    "split": "train",
                    "languages": ["en"],
                    "paper_core": True,
                    "audit_status": "audited",
                    "snapshot_path": source_path.name,
                    "sha256": _sha256(source_path),
                    "bytes": source_path.stat().st_size,
                    "expected_tool_count": 1,
                    "ground_truth_path": ground_truth_path.name,
                    "ground_truth_sha256": _sha256(ground_truth_path),
                    "license": {
                        "spdx_id": "MIT",
                        "evidence_url": "https://example.invalid/license",
                    },
                    "audit": {
                        "reviewer": "test",
                        "reviewed_at": "2026-07-27",
                        "checks": ["license", "revision", "redistribution"],
                    },
                    "provenance": {
                        "kind": "project-authored-fixture",
                        "upstream_url": "https://example.invalid/source",
                        "revision": "test-v1",
                    },
                }
            ],
        },
    )
    return manifest_path, source_path


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _issue_codes(report: corpus_manifest.CorpusReport) -> set[str]:
    return {issue.code for issue in report.issues}
