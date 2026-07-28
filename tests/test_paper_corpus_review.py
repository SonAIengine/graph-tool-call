"""Tests for supplemental paper-corpus review artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.corpus.review import validate_manifest_reviews, validate_review_artifact


def test_internal_ai_review_covers_every_case_without_claiming_human_review() -> None:
    reports = validate_manifest_reviews()

    assert len(reports) == 1
    report = reports[0]
    assert report.valid is True
    assert report.reviewer_kind == "ai-assisted"
    assert report.expected_case_count == 35
    assert report.reviewed_case_count == 35
    assert report.approved_case_count == 35
    assert report.disagreement_count == 0
    assert report.held_out_expected_case_count == 6
    assert report.held_out_reviewed_case_count == 6
    assert report.counts_toward_human_review_gate is False


def test_ai_review_cannot_claim_independent_human_gate(tmp_path: Path) -> None:
    manifest_path, review_path = _copy_review_fixture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["counts_toward_human_review_gate"] = True
    _write_json(review_path, review)

    report = validate_review_artifact(review_path, manifest_path=manifest_path)

    assert report.valid is False
    assert "review_human_gate_claim_invalid" in _issue_codes(report)


def test_review_detects_ground_truth_snapshot_change(tmp_path: Path) -> None:
    manifest_path, review_path = _copy_review_fixture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["source_reviews"][0]["ground_truth_sha256"] = "0" * 64
    _write_json(review_path, review)

    report = validate_review_artifact(review_path, manifest_path=manifest_path)

    assert report.valid is False
    assert "review_ground_truth_digest_mismatch" in _issue_codes(report)


def test_review_detects_missing_case(tmp_path: Path) -> None:
    manifest_path, review_path = _copy_review_fixture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["source_reviews"][0]["decisions"].pop()
    _write_json(review_path, review)

    report = validate_review_artifact(review_path, manifest_path=manifest_path)

    assert report.valid is False
    assert "review_case_coverage_incomplete" in _issue_codes(report)


def _copy_review_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = repository_root / "benchmarks/corpus/manifest.json"
    source_review = repository_root / "benchmarks/corpus/reviews/internal_ai_consistency_v1.json"

    review_path = tmp_path / "review.json"
    review_path.write_bytes(source_review.read_bytes())
    return manifest_path, review_path


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}
