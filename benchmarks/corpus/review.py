"""Validate supplemental annotation-review artifacts.

Supplemental reviews make author or AI-assisted consistency checks auditable.
They never count as independent human review unless the artifact explicitly
declares ``reviewer_kind=human-independent``. The paper corpus manifest remains
the authority for the publication gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.corpus.manifest import DEFAULT_MANIFEST_PATH, load_corpus_manifest

ALLOWED_REVIEWER_KINDS = frozenset({"ai-assisted", "human-author", "human-independent"})
REQUIRED_CHECKS = frozenset(
    {
        "acceptable_alternatives",
        "producer_role",
        "query_clarity",
        "target_semantics",
    }
)


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    message: str
    source_id: str | None = None
    case_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewReport:
    review_path: str
    review_id: str = ""
    reviewer_kind: str = ""
    expected_case_count: int = 0
    reviewed_case_count: int = 0
    approved_case_count: int = 0
    disagreement_count: int = 0
    held_out_expected_case_count: int = 0
    held_out_reviewed_case_count: int = 0
    counts_toward_human_review_gate: bool = False
    issues: list[ReviewIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_path": self.review_path,
            "review_id": self.review_id,
            "reviewer_kind": self.reviewer_kind,
            "valid": self.valid,
            "expected_case_count": self.expected_case_count,
            "reviewed_case_count": self.reviewed_case_count,
            "approved_case_count": self.approved_case_count,
            "disagreement_count": self.disagreement_count,
            "held_out_expected_case_count": self.held_out_expected_case_count,
            "held_out_reviewed_case_count": self.held_out_reviewed_case_count,
            "counts_toward_human_review_gate": self.counts_toward_human_review_gate,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_review_artifact(
    review_path: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> ReviewReport:
    """Validate one supplemental review against exact ground-truth snapshots."""
    review_file = Path(review_path).resolve()
    manifest_file = Path(manifest_path).resolve()
    report = ReviewReport(review_path=str(review_file))
    review = _load_json(review_file, report, "review_artifact_invalid")
    if review is None:
        return report
    manifest = load_corpus_manifest(manifest_file)

    if review.get("schema_version") != 1:
        _add(report, "review_schema_version_unsupported", "Review schema_version must be 1.")
    report.review_id = _string(review.get("review_id"))
    if not report.review_id:
        _add(report, "review_id_missing", "Review artifact must have a stable review_id.")
    if review.get("corpus_id") != manifest.get("corpus_id"):
        _add(
            report,
            "review_corpus_mismatch",
            "Review corpus_id must match the corpus manifest.",
            evidence={"expected": manifest.get("corpus_id"), "actual": review.get("corpus_id")},
        )
    for key in ("protocol", "reviewed_at"):
        if not _string(review.get(key)):
            _add(report, f"review_{key}_missing", f"Review artifact must record {key}.")

    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        _add(report, "reviewer_missing", "Review artifact must describe its reviewer.")
        reviewer = {}
    report.reviewer_kind = _string(reviewer.get("kind"))
    if report.reviewer_kind not in ALLOWED_REVIEWER_KINDS:
        _add(
            report,
            "reviewer_kind_invalid",
            "reviewer.kind must use the frozen reviewer taxonomy.",
            evidence={"allowed": sorted(ALLOWED_REVIEWER_KINDS), "actual": report.reviewer_kind},
        )
    if not _string(reviewer.get("identity")):
        _add(report, "reviewer_identity_missing", "Review artifact must name its reviewer.")
    declared_human_gate = review.get("counts_toward_human_review_gate")
    expected_human_gate = report.reviewer_kind == "human-independent"
    report.counts_toward_human_review_gate = declared_human_gate is True
    if declared_human_gate is not expected_human_gate:
        _add(
            report,
            "review_human_gate_claim_invalid",
            "Only an independent human review may count toward the human review gate.",
            evidence={
                "reviewer_kind": report.reviewer_kind,
                "declared": declared_human_gate,
                "expected": expected_human_gate,
            },
        )

    checks = review.get("checks")
    if (
        not isinstance(checks, list)
        or not all(isinstance(check, str) for check in checks)
        or not REQUIRED_CHECKS.issubset(set(checks))
    ):
        _add(
            report,
            "review_checks_incomplete",
            "Review must cover query, target, producer, and alternative semantics.",
            evidence={"required": sorted(REQUIRED_CHECKS)},
        )
    if review.get("retrieval_results_inspected") is not False:
        _add(
            report,
            "review_retrieval_blinding_missing",
            "Consistency review must state that retrieval outcomes were not inspected.",
        )

    sources = manifest.get("sources") or []
    source_index = {
        _string(source.get("id")): source for source in sources if isinstance(source, dict)
    }
    expected_cases: dict[str, set[str]] = {}
    ground_truth_digests: dict[str, str] = {}
    held_out_cases: set[str] = set()
    for source_id, source in source_index.items():
        gt_path = (manifest_file.parent / _string(source.get("ground_truth_path"))).resolve()
        ground_truth = _read_ground_truth(gt_path, report, source_id)
        actual_digest = _sha256(gt_path)
        declared_digest = _string(source.get("ground_truth_sha256"))
        ground_truth_digests[source_id] = actual_digest
        if actual_digest != declared_digest:
            _add(
                report,
                "review_manifest_ground_truth_digest_mismatch",
                "Manifest ground-truth digest does not match the file under review.",
                source_id=source_id,
                evidence={"manifest": declared_digest, "actual": actual_digest},
            )
        case_ids = {
            _string(case.get("case_id"))
            for case in ground_truth.get("cases", [])
            if isinstance(case, dict) and _string(case.get("case_id"))
        }
        expected_cases[source_id] = case_ids
        if source.get("evaluation_role") == "held-out":
            held_out_cases.update(case_ids)

    report.expected_case_count = sum(len(case_ids) for case_ids in expected_cases.values())
    report.held_out_expected_case_count = len(held_out_cases)
    seen_cases: set[str] = set()
    source_reviews = review.get("source_reviews")
    if not isinstance(source_reviews, list):
        _add(report, "review_sources_invalid", "source_reviews must be a list.")
        source_reviews = []

    for source_review in source_reviews:
        if not isinstance(source_review, dict):
            _add(report, "review_source_row_invalid", "Every source review must be an object.")
            continue
        source_id = _string(source_review.get("source_id"))
        source = source_index.get(source_id)
        if source is None:
            _add(
                report,
                "review_source_unknown",
                "Review references an unknown corpus source.",
                source_id=source_id or None,
            )
            continue
        expected_digest = ground_truth_digests.get(source_id, "")
        actual_digest = _string(source_review.get("ground_truth_sha256"))
        if actual_digest != expected_digest:
            _add(
                report,
                "review_ground_truth_digest_mismatch",
                "Review must bind to the exact annotated ground-truth snapshot.",
                source_id=source_id,
                evidence={"expected": expected_digest, "actual": actual_digest},
            )
        decisions = source_review.get("decisions")
        if not isinstance(decisions, list):
            _add(
                report,
                "review_decisions_invalid",
                "Source review decisions must be a list.",
                source_id=source_id,
            )
            continue
        for decision in decisions:
            if not isinstance(decision, dict):
                _add(
                    report,
                    "review_decision_invalid",
                    "Every case decision must be an object.",
                    source_id=source_id,
                )
                continue
            case_id = _string(decision.get("case_id"))
            if case_id not in expected_cases[source_id]:
                _add(
                    report,
                    "review_case_unknown",
                    "Review references a case outside the source ground truth.",
                    source_id=source_id,
                    case_id=case_id or None,
                )
                continue
            if case_id in seen_cases:
                _add(
                    report,
                    "review_case_duplicate",
                    "Each case may appear only once in a review artifact.",
                    source_id=source_id,
                    case_id=case_id,
                )
                continue
            seen_cases.add(case_id)
            verdict = decision.get("verdict")
            if verdict not in {"approved", "disagreement"}:
                _add(
                    report,
                    "review_verdict_invalid",
                    "Case verdict must be approved or disagreement.",
                    source_id=source_id,
                    case_id=case_id,
                )
            elif verdict == "approved":
                report.approved_case_count += 1
            else:
                report.disagreement_count += 1
                if not _string(decision.get("notes")):
                    _add(
                        report,
                        "review_disagreement_notes_missing",
                        "A disagreement must explain the proposed correction.",
                        source_id=source_id,
                        case_id=case_id,
                    )

    report.reviewed_case_count = len(seen_cases)
    report.held_out_reviewed_case_count = len(seen_cases & held_out_cases)
    all_expected = set().union(*expected_cases.values()) if expected_cases else set()
    missing = sorted(all_expected - seen_cases)
    if missing:
        _add(
            report,
            "review_case_coverage_incomplete",
            "Review must include every corpus annotation.",
            evidence={"missing_count": len(missing), "missing": missing},
        )
    return report


def validate_manifest_reviews(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[ReviewReport]:
    """Validate every supplemental review declared by a corpus manifest."""
    manifest_file = Path(manifest_path).resolve()
    manifest = load_corpus_manifest(manifest_file)
    rows = manifest.get("supplemental_annotation_reviews") or []
    reports: list[ReviewReport] = []
    for row in rows:
        if not isinstance(row, dict) or not _string(row.get("path")):
            report = ReviewReport(review_path="")
            _add(
                report,
                "review_manifest_entry_invalid",
                "Every supplemental review entry must contain a path.",
            )
            reports.append(report)
            continue
        path = (manifest_file.parent / _string(row["path"])).resolve()
        report = validate_review_artifact(path, manifest_path=manifest_file)
        declared_sha = _string(row.get("sha256"))
        if not declared_sha or _sha256(path) != declared_sha:
            _add(
                report,
                "review_artifact_digest_mismatch",
                "Supplemental review digest does not match the manifest.",
            )
        reports.append(report)
    return reports


def _load_json(path: Path, report: ReviewReport, code: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _add(report, code, f"Unable to read valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        _add(report, code, "JSON root must be an object.")
        return None
    return value


def _read_ground_truth(path: Path, report: ReviewReport, source_id: str) -> dict[str, Any]:
    value = _load_json(path, report, "review_ground_truth_invalid")
    if value is None:
        _add(
            report,
            "review_ground_truth_unavailable",
            "Unable to inspect source ground truth.",
            source_id=source_id,
        )
        return {}
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _string(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _add(
    report: ReviewReport,
    code: str,
    message: str,
    *,
    source_id: str | None = None,
    case_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    report.issues.append(
        ReviewIssue(
            code=code,
            message=message,
            source_id=source_id,
            case_id=case_id,
            evidence=evidence or {},
        )
    )


def _format_report(report: ReviewReport) -> str:
    lines = [
        f"review={report.review_id or '<unknown>'}",
        f"valid={'pass' if report.valid else 'fail'}",
        f"reviewer_kind={report.reviewer_kind or '<unknown>'}",
        f"coverage={report.reviewed_case_count}/{report.expected_case_count}",
        f"approved={report.approved_case_count}",
        f"disagreements={report.disagreement_count}",
        (
            "held_out_annotation_checks="
            f"{report.held_out_reviewed_case_count}/{report.held_out_expected_case_count}"
        ),
        f"counts_toward_human_review_gate={report.counts_toward_human_review_gate}",
    ]
    lines.extend(f"[error] {issue.code}: {issue.message}" for issue in report.issues)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reports = (
        [validate_review_artifact(args.review, manifest_path=args.manifest)]
        if args.review
        else validate_manifest_reviews(args.manifest)
    )
    if args.json:
        print(json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(_format_report(report) for report in reports))
    return 0 if reports and all(report.valid for report in reports) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
