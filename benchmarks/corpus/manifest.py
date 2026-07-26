"""Validate the public heterogeneous paper-corpus manifest.

The validator separates artifact integrity from paper readiness. A small seed
corpus can be reproducible and legally auditable without being large or diverse
enough to support a general research claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from graph_tool_call import ingest_source

DEFAULT_MANIFEST_PATH = Path(__file__).with_name("manifest.json")
ALLOWED_SPLITS = frozenset({"train", "dev", "test"})
ALLOWED_AUDIT_STATUSES = frozenset({"audited", "pending", "excluded"})
ALLOWED_EVALUATION_ROLES = frozenset({"development", "held-out"})
ALLOWED_SOURCE_TYPES = frozenset(
    {
        "graphql-introspection",
        "mcp",
        "openapi",
        "python",
        "tool-catalog",
    }
)
ALLOWED_PROVENANCE_KINDS = frozenset(
    {
        "external-snapshot",
        "project-authored-fixture",
        "derived-snapshot",
    }
)
ALLOWED_CASE_ORIGINS = frozenset(
    {
        "execution-derived",
        "human-authored",
        "human-authored-bilingual",
        "synthetic",
    }
)
SOURCE_TYPE_ADAPTERS = {
    "graphql-introspection": "graphql-introspection",
    "mcp": "mcp-tools",
    "openapi": "openapi",
    "python": "python-functions",
    "tool-catalog": "tool-catalog",
}
REQUIRED_ANNOTATION_AUDIT_CHECKS = frozenset(
    {
        "producer_role",
        "query_clarity",
        "target_exists",
    }
)


class CorpusManifestError(ValueError):
    """Raised when a corpus manifest cannot be parsed."""


@dataclass(frozen=True)
class CorpusIssue:
    """One stable corpus integrity or paper-readiness diagnostic."""

    severity: str
    code: str
    message: str
    scope: str = "integrity"
    source_id: str | None = None
    case_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorpusReport:
    """Normalized validation report for one corpus manifest."""

    manifest_path: str
    corpus_id: str = ""
    schema_version: int | None = None
    source_count: int = 0
    paper_core_source_count: int = 0
    held_out_source_count: int = 0
    family_count: int = 0
    query_count: int = 0
    annotation_reviewer_count: int = 0
    source_type_counts: dict[str, int] = field(default_factory=dict)
    paper_core_source_type_counts: dict[str, int] = field(default_factory=dict)
    split_source_counts: dict[str, int] = field(default_factory=dict)
    split_query_counts: dict[str, int] = field(default_factory=dict)
    paper_core_split_query_counts: dict[str, int] = field(default_factory=dict)
    source_profiles: list[dict[str, Any]] = field(default_factory=list)
    issues: list[CorpusIssue] = field(default_factory=list)

    @property
    def integrity_ready(self) -> bool:
        return not any(
            issue.scope == "integrity" and issue.severity == "blocker" for issue in self.issues
        )

    @property
    def paper_ready(self) -> bool:
        return self.integrity_ready and not any(
            issue.scope == "paper_readiness" and issue.severity == "blocker"
            for issue in self.issues
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "corpus_id": self.corpus_id,
            "schema_version": self.schema_version,
            "integrity_ready": self.integrity_ready,
            "paper_ready": self.paper_ready,
            "source_count": self.source_count,
            "paper_core_source_count": self.paper_core_source_count,
            "held_out_source_count": self.held_out_source_count,
            "family_count": self.family_count,
            "query_count": self.query_count,
            "annotation_reviewer_count": self.annotation_reviewer_count,
            "source_type_counts": self.source_type_counts,
            "paper_core_source_type_counts": self.paper_core_source_type_counts,
            "split_source_counts": self.split_source_counts,
            "split_query_counts": self.split_query_counts,
            "paper_core_split_query_counts": self.paper_core_split_query_counts,
            "source_profiles": self.source_profiles,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def load_corpus_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load a corpus manifest as JSON without validating referenced artifacts."""
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CorpusManifestError(f"Unable to read corpus manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CorpusManifestError(f"Corpus manifest is not valid JSON: {path}") from exc
    if not isinstance(manifest, dict):
        raise CorpusManifestError(f"Corpus manifest root must be an object: {path}")
    return manifest


def validate_corpus_manifest(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    verify_hashes: bool = True,
    verify_ingest: bool = False,
) -> CorpusReport:
    """Validate corpus provenance, splits, annotations, and optional ingest."""
    path = Path(manifest_path).resolve()
    report = CorpusReport(manifest_path=str(path))
    try:
        manifest = load_corpus_manifest(path)
    except CorpusManifestError as exc:
        report.issues.append(_issue("manifest_invalid", str(exc)))
        return report

    report.corpus_id = _required_string(
        manifest.get("corpus_id"),
        "corpus_id",
        report,
    )
    schema_version = manifest.get("schema_version")
    if schema_version != 1:
        report.issues.append(
            _issue(
                "manifest_schema_version_unsupported",
                "Corpus manifest schema_version must be 1.",
                evidence={"actual": schema_version},
            )
        )
    else:
        report.schema_version = schema_version
    _validate_split_policy(manifest.get("split_policy"), report=report)
    if not verify_hashes:
        report.issues.append(
            CorpusIssue(
                severity="blocker",
                code="hash_verification_disabled",
                message=(
                    "Hash verification is disabled. This run can inspect structure "
                    "but cannot establish paper readiness."
                ),
                scope="paper_readiness",
            )
        )
    if not verify_ingest:
        report.issues.append(
            CorpusIssue(
                severity="blocker",
                code="ingest_verification_disabled",
                message=(
                    "Ingest verification is disabled. This run can inspect corpus "
                    "metadata but cannot establish paper readiness."
                ),
                scope="paper_readiness",
            )
        )

    repository_root = _repository_root(path, manifest, report)
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        report.issues.append(
            _issue(
                "manifest_sources_missing", "Corpus manifest must contain a non-empty sources list."
            )
        )
        return report

    source_ids: set[str] = set()
    case_ids: set[str] = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    family_source_types: dict[str, str] = {}
    paper_core_source_type_families: dict[str, set[str]] = defaultdict(set)
    source_type_counts: Counter[str] = Counter()
    paper_core_source_type_counts: Counter[str] = Counter()
    split_source_counts: Counter[str] = Counter()
    split_query_counts: Counter[str] = Counter()
    paper_core_split_query_counts: Counter[str] = Counter()
    paper_core_source_count = 0
    held_out_source_count = 0
    annotation_reviewers: set[str] = set()

    for index, raw_source in enumerate(sources):
        if not isinstance(raw_source, dict):
            report.issues.append(
                _issue(
                    "source_row_invalid",
                    "Every corpus source row must be an object.",
                    evidence={"index": index},
                )
            )
            continue
        profile = _validate_source(
            raw_source,
            manifest_path=path,
            repository_root=repository_root,
            verify_hashes=verify_hashes,
            verify_ingest=verify_ingest,
            report=report,
            source_ids=source_ids,
            case_ids=case_ids,
        )
        report.source_profiles.append(profile)
        source_id = profile.get("source_id")
        family_id = profile.get("family_id")
        source_type = profile.get("source_type")
        split = profile.get("split")
        query_count = int(profile.get("query_count") or 0)
        if source_id:
            source_ids.add(str(source_id))
        if family_id and split:
            family_splits[str(family_id)].add(str(split))
        if family_id and source_type:
            previous_type = family_source_types.setdefault(str(family_id), str(source_type))
            if previous_type != source_type:
                report.issues.append(
                    _issue(
                        "family_source_type_conflict",
                        "One API family cannot change source_type across snapshots.",
                        source_id=str(source_id or ""),
                        evidence={
                            "family_id": family_id,
                            "first": previous_type,
                            "actual": source_type,
                        },
                    )
                )
        if source_type:
            source_type_counts[str(source_type)] += 1
        if split:
            split_source_counts[str(split)] += 1
            split_query_counts[str(split)] += query_count
        if profile.get("paper_core"):
            paper_core_source_count += 1
            if source_type and family_id:
                paper_core_source_type_counts[str(source_type)] += 1
                paper_core_source_type_families[str(source_type)].add(str(family_id))
            if split:
                paper_core_split_query_counts[str(split)] += query_count
        if profile.get("evaluation_role") == "held-out":
            held_out_source_count += 1
        annotation_reviewers.update(profile.get("annotation_reviewers") or [])

    for profile in report.source_profiles:
        unknown_references = sorted(set(profile.get("ground_truth_source_ids") or []) - source_ids)
        if unknown_references:
            report.issues.append(
                _issue(
                    "ground_truth_unknown_source",
                    "Ground truth references source IDs absent from the manifest.",
                    source_id=str(profile.get("source_id") or ""),
                    evidence={"unknown_source_ids": unknown_references},
                )
            )

    for family_id, splits in sorted(family_splits.items()):
        if len(splits) > 1:
            report.issues.append(
                _issue(
                    "family_split_leakage",
                    "All snapshots and query variants from one API family must stay in one split.",
                    evidence={"family_id": family_id, "splits": sorted(splits)},
                )
            )

    report.source_count = len(report.source_profiles)
    report.paper_core_source_count = paper_core_source_count
    report.held_out_source_count = held_out_source_count
    report.family_count = len(family_splits)
    report.query_count = sum(split_query_counts.values())
    report.annotation_reviewer_count = len(annotation_reviewers)
    report.source_type_counts = dict(sorted(source_type_counts.items()))
    report.paper_core_source_type_counts = dict(sorted(paper_core_source_type_counts.items()))
    report.split_source_counts = _complete_split_counts(split_source_counts)
    report.split_query_counts = _complete_split_counts(split_query_counts)
    report.paper_core_split_query_counts = _complete_split_counts(paper_core_split_query_counts)

    _validate_paper_readiness(
        manifest,
        report=report,
        family_splits=family_splits,
        source_type_families=paper_core_source_type_families,
    )
    return report


def _validate_source(
    source: dict[str, Any],
    *,
    manifest_path: Path,
    repository_root: Path,
    verify_hashes: bool,
    verify_ingest: bool,
    report: CorpusReport,
    source_ids: set[str],
    case_ids: set[str],
) -> dict[str, Any]:
    source_id = _source_string(source, "id", report)
    family_id = _source_string(source, "family_id", report, source_id=source_id)
    source_type = _source_string(source, "source_type", report, source_id=source_id)
    split = _source_string(source, "split", report, source_id=source_id)
    evaluation_role = _source_string(
        source,
        "evaluation_role",
        report,
        source_id=source_id,
    )
    profile: dict[str, Any] = {
        "source_id": source_id,
        "family_id": family_id,
        "source_type": source_type,
        "split": split,
        "evaluation_role": evaluation_role,
        "paper_core": bool(source.get("paper_core")),
        "query_count": 0,
    }

    if source_id in source_ids:
        report.issues.append(
            _issue(
                "source_id_duplicate",
                "Corpus source IDs must be unique.",
                source_id=source_id,
            )
        )
    if source_type and source_type not in ALLOWED_SOURCE_TYPES:
        report.issues.append(
            _issue(
                "source_type_unsupported",
                "Corpus source_type is not supported by the manifest schema.",
                source_id=source_id,
                evidence={"actual": source_type, "allowed": sorted(ALLOWED_SOURCE_TYPES)},
            )
        )
    adapter = source.get("adapter")
    expected_adapter = SOURCE_TYPE_ADAPTERS.get(source_type)
    if expected_adapter is not None and adapter != expected_adapter:
        report.issues.append(
            _issue(
                "source_adapter_mismatch",
                "Declared adapter does not match the source_type contract.",
                source_id=source_id,
                evidence={"expected": expected_adapter, "actual": adapter},
            )
        )
    if split and split not in ALLOWED_SPLITS:
        report.issues.append(
            _issue(
                "source_split_invalid",
                "Corpus source split must be train, dev, or test.",
                source_id=source_id,
                evidence={"actual": split},
            )
        )
    if evaluation_role and evaluation_role not in ALLOWED_EVALUATION_ROLES:
        report.issues.append(
            _issue(
                "source_evaluation_role_invalid",
                "Corpus source evaluation_role must be development or held-out.",
                source_id=source_id,
                evidence={
                    "actual": evaluation_role,
                    "allowed": sorted(ALLOWED_EVALUATION_ROLES),
                },
            )
        )
    expected_evaluation_role = "held-out" if split == "test" else "development"
    if evaluation_role and split in ALLOWED_SPLITS and evaluation_role != expected_evaluation_role:
        report.issues.append(
            _issue(
                "source_evaluation_role_mismatch",
                "Test families must be held-out; train and dev families are development data.",
                source_id=source_id,
                evidence={
                    "split": split,
                    "expected": expected_evaluation_role,
                    "actual": evaluation_role,
                },
            )
        )

    audit_status = source.get("audit_status")
    if audit_status not in ALLOWED_AUDIT_STATUSES:
        report.issues.append(
            _issue(
                "source_audit_status_invalid",
                "Source audit_status must be audited, pending, or excluded.",
                source_id=source_id,
                evidence={"actual": audit_status},
            )
        )
    if source.get("paper_core") and audit_status != "audited":
        report.issues.append(
            _issue(
                "paper_core_source_not_audited",
                "A paper_core source must have audited provenance and licensing.",
                source_id=source_id,
            )
        )

    _validate_license(source.get("license"), source_id=source_id, report=report)
    _validate_provenance(source.get("provenance"), source_id=source_id, report=report)
    _validate_audit(
        source.get("audit"),
        source_id=source_id,
        required=bool(source.get("paper_core")),
        report=report,
    )

    snapshot_path = _resolve_artifact_path(
        source.get("snapshot_path"),
        field_name="snapshot_path",
        manifest_path=manifest_path,
        repository_root=repository_root,
        source_id=source_id,
        report=report,
    )
    if snapshot_path is not None:
        profile["snapshot_path"] = str(snapshot_path)
        _validate_file_fingerprint(
            snapshot_path,
            expected_sha256=source.get("sha256"),
            expected_bytes=source.get("bytes"),
            verify_hashes=verify_hashes,
            source_id=source_id,
            code_prefix="snapshot",
            report=report,
        )

    ground_truth_path = _resolve_artifact_path(
        source.get("ground_truth_path"),
        field_name="ground_truth_path",
        manifest_path=manifest_path,
        repository_root=repository_root,
        source_id=source_id,
        report=report,
    )
    expected_names: set[str] = set()
    if ground_truth_path is not None:
        profile["ground_truth_path"] = str(ground_truth_path)
        _validate_file_fingerprint(
            ground_truth_path,
            expected_sha256=source.get("ground_truth_sha256"),
            expected_bytes=None,
            verify_hashes=verify_hashes,
            source_id=source_id,
            code_prefix="ground_truth",
            report=report,
        )
        (
            query_count,
            expected_names,
            ground_truth_source_ids,
            annotation_reviewers,
        ) = _validate_ground_truth(
            ground_truth_path,
            source_id=source_id,
            family_id=family_id,
            split=split,
            global_case_ids=case_ids,
            report=report,
        )
        profile["query_count"] = query_count
        profile["ground_truth_source_ids"] = ground_truth_source_ids
        profile["annotation_reviewers"] = annotation_reviewers
    elif source.get("paper_core"):
        report.issues.append(
            _issue(
                "paper_core_ground_truth_missing",
                "A paper_core source must reference annotated ground truth.",
                source_id=source_id,
            )
        )

    if verify_ingest and snapshot_path is not None:
        _validate_ingest(
            source,
            snapshot_path=snapshot_path,
            expected_names=expected_names,
            source_id=source_id,
            profile=profile,
            report=report,
        )
    return profile


def _validate_split_policy(value: Any, *, report: CorpusReport) -> None:
    if not isinstance(value, dict):
        report.issues.append(
            _issue(
                "split_policy_missing",
                "Corpus manifest must define its frozen API-family split policy.",
            )
        )
        return
    expected_values = {
        "unit": "api_family",
        "test_access_policy": "held-out-no-tuning",
    }
    for field_name, expected in expected_values.items():
        if value.get(field_name) != expected:
            report.issues.append(
                _issue(
                    f"split_policy_{field_name}_invalid",
                    f"split_policy {field_name} must be {expected}.",
                    evidence={"actual": value.get(field_name), "expected": expected},
                )
            )
    if not isinstance(value.get("frozen_at"), str) or not value["frozen_at"].strip():
        report.issues.append(
            _issue(
                "split_policy_frozen_at_missing",
                "Corpus split policy must record when family assignments were frozen.",
            )
        )


def _validate_license(value: Any, *, source_id: str, report: CorpusReport) -> None:
    if not isinstance(value, dict):
        report.issues.append(
            _issue(
                "source_license_missing",
                "Every corpus source must declare license metadata.",
                source_id=source_id,
            )
        )
        return
    for field_name in ("spdx_id", "evidence_url"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            report.issues.append(
                _issue(
                    f"source_license_{field_name}_missing",
                    f"Source license must include {field_name}.",
                    source_id=source_id,
                )
            )


def _validate_provenance(value: Any, *, source_id: str, report: CorpusReport) -> None:
    if not isinstance(value, dict):
        report.issues.append(
            _issue(
                "source_provenance_missing",
                "Every corpus source must declare provenance metadata.",
                source_id=source_id,
            )
        )
        return
    kind = value.get("kind")
    if kind not in ALLOWED_PROVENANCE_KINDS:
        report.issues.append(
            _issue(
                "source_provenance_kind_invalid",
                "Source provenance kind is unsupported.",
                source_id=source_id,
                evidence={"actual": kind, "allowed": sorted(ALLOWED_PROVENANCE_KINDS)},
            )
        )
    for field_name in ("upstream_url", "revision"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            report.issues.append(
                _issue(
                    f"source_provenance_{field_name}_missing",
                    f"Source provenance must include {field_name}.",
                    source_id=source_id,
                )
            )


def _validate_audit(
    value: Any,
    *,
    source_id: str,
    required: bool,
    report: CorpusReport,
) -> None:
    if not required and value is None:
        return
    if not isinstance(value, dict):
        report.issues.append(
            _issue(
                "source_audit_missing",
                "A paper_core source must record its provenance audit trail.",
                source_id=source_id,
            )
        )
        return
    for field_name in ("reviewer", "reviewed_at"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            report.issues.append(
                _issue(
                    f"source_audit_{field_name}_missing",
                    f"Source audit must include {field_name}.",
                    source_id=source_id,
                )
            )
    checks = value.get("checks")
    required_checks = {"license", "revision", "redistribution"}
    if (
        not isinstance(checks, list)
        or not all(isinstance(check, str) for check in checks)
        or not required_checks.issubset(set(checks))
    ):
        report.issues.append(
            _issue(
                "source_audit_checks_incomplete",
                "Source audit must cover license, revision, and redistribution.",
                source_id=source_id,
                evidence={"required": sorted(required_checks)},
            )
        )


def _validate_ground_truth(
    path: Path,
    *,
    source_id: str,
    family_id: str,
    split: str,
    global_case_ids: set[str],
    report: CorpusReport,
) -> tuple[int, set[str], list[str], list[str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report.issues.append(
            _issue(
                "ground_truth_invalid",
                "Ground-truth file must contain valid UTF-8 JSON.",
                source_id=source_id,
            )
        )
        return 0, set(), [], []
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        report.issues.append(
            _issue(
                "ground_truth_schema_invalid",
                "Ground truth must use paper corpus schema_version 1.",
                source_id=source_id,
            )
        )
        return 0, set(), [], []
    if document.get("family_id") != family_id or document.get("split") != split:
        report.issues.append(
            _issue(
                "ground_truth_partition_mismatch",
                "Ground-truth family_id and split must match the source manifest.",
                source_id=source_id,
                evidence={
                    "expected_family_id": family_id,
                    "actual_family_id": document.get("family_id"),
                    "expected_split": split,
                    "actual_split": document.get("split"),
                },
            )
        )
    document_source_ids = document.get("source_ids")
    if not isinstance(document_source_ids, list) or not all(
        isinstance(value, str) and value.strip() for value in document_source_ids
    ):
        report.issues.append(
            _issue(
                "ground_truth_source_ids_invalid",
                "Ground-truth source_ids must be a list of non-empty manifest IDs.",
                source_id=source_id,
            )
        )
        normalized_source_ids: list[str] = []
    else:
        normalized_source_ids = [str(value) for value in document_source_ids]
    if source_id not in normalized_source_ids:
        report.issues.append(
            _issue(
                "ground_truth_source_missing",
                "Ground truth must reference its manifest source ID.",
                source_id=source_id,
            )
        )

    annotation_reviewers = _validate_annotation_audit(
        document.get("annotation_audit"),
        source_id=source_id,
        report=report,
    )

    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        report.issues.append(
            _issue(
                "ground_truth_cases_missing",
                "Ground truth must contain a non-empty cases list.",
                source_id=source_id,
            )
        )
        return 0, set(), normalized_source_ids, annotation_reviewers

    expected_names: set[str] = set()
    local_case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            report.issues.append(
                _issue(
                    "ground_truth_case_invalid",
                    "Every ground-truth case must be an object.",
                    source_id=source_id,
                    evidence={"index": index},
                )
            )
            continue
        case_id = str(case.get("case_id") or "").strip()
        query = str(case.get("query") or "").strip()
        if not case_id:
            report.issues.append(
                _issue(
                    "ground_truth_case_id_missing",
                    "Every ground-truth case must have a stable case_id.",
                    source_id=source_id,
                    evidence={"index": index},
                )
            )
        elif case_id in local_case_ids or case_id in global_case_ids:
            report.issues.append(
                _issue(
                    "ground_truth_case_id_duplicate",
                    "Ground-truth case IDs must be globally unique.",
                    source_id=source_id,
                    case_id=case_id,
                )
            )
        else:
            local_case_ids.add(case_id)
            global_case_ids.add(case_id)
        if not query:
            report.issues.append(
                _issue(
                    "ground_truth_query_missing",
                    "Every ground-truth case must have a query.",
                    source_id=source_id,
                    case_id=case_id or None,
                )
            )
        targets = case.get("expected_targets")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(name, str) and name.strip() for name in targets)
        ):
            report.issues.append(
                _issue(
                    "ground_truth_targets_invalid",
                    "expected_targets must be a non-empty list of tool names.",
                    source_id=source_id,
                    case_id=case_id or None,
                )
            )
        else:
            expected_names.update(str(name) for name in targets)
        for optional_field in ("acceptable_alternatives", "required_producers"):
            values = case.get(optional_field, [])
            if not isinstance(values, list) or not all(
                isinstance(name, str) and name.strip() for name in values
            ):
                report.issues.append(
                    _issue(
                        f"ground_truth_{optional_field}_invalid",
                        f"{optional_field} must be a list of tool names.",
                        source_id=source_id,
                        case_id=case_id or None,
                    )
                )
            else:
                expected_names.update(str(name) for name in values)
        provenance = case.get("provenance")
        if (
            not isinstance(provenance, dict)
            or not provenance.get("origin")
            or not provenance.get("annotator_version")
        ):
            report.issues.append(
                _issue(
                    "ground_truth_provenance_missing",
                    "Every case must record origin and annotator_version.",
                    source_id=source_id,
                    case_id=case_id or None,
                )
            )
        elif provenance.get("origin") not in ALLOWED_CASE_ORIGINS:
            report.issues.append(
                _issue(
                    "ground_truth_origin_invalid",
                    "Case provenance origin is not part of the frozen annotation taxonomy.",
                    source_id=source_id,
                    case_id=case_id or None,
                    evidence={
                        "actual": provenance.get("origin"),
                        "allowed": sorted(ALLOWED_CASE_ORIGINS),
                    },
                )
            )
    return len(cases), expected_names, normalized_source_ids, annotation_reviewers


def _validate_annotation_audit(
    value: Any,
    *,
    source_id: str,
    report: CorpusReport,
) -> list[str]:
    if not isinstance(value, dict):
        report.issues.append(
            _issue(
                "ground_truth_annotation_audit_missing",
                "Paper ground truth must record its human annotation audit.",
                source_id=source_id,
            )
        )
        return []
    reviewers = value.get("reviewers")
    if not isinstance(reviewers, list) or not all(
        isinstance(reviewer, str) and reviewer.strip() for reviewer in reviewers
    ):
        report.issues.append(
            _issue(
                "ground_truth_annotation_reviewers_invalid",
                "annotation_audit reviewers must be a list of non-empty identities.",
                source_id=source_id,
            )
        )
        normalized_reviewers: list[str] = []
    else:
        normalized_reviewers = sorted({str(reviewer).strip().casefold() for reviewer in reviewers})
    for field_name in ("reviewed_at", "protocol"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            report.issues.append(
                _issue(
                    f"ground_truth_annotation_{field_name}_missing",
                    f"annotation_audit must include {field_name}.",
                    source_id=source_id,
                )
            )
    checks = value.get("checks")
    if (
        not isinstance(checks, list)
        or not all(isinstance(check, str) for check in checks)
        or not REQUIRED_ANNOTATION_AUDIT_CHECKS.issubset(set(checks))
    ):
        report.issues.append(
            _issue(
                "ground_truth_annotation_checks_incomplete",
                "Annotation audit must check query clarity, target existence, and producer roles.",
                source_id=source_id,
                evidence={"required": sorted(REQUIRED_ANNOTATION_AUDIT_CHECKS)},
            )
        )
    return normalized_reviewers


def _validate_ingest(
    source: dict[str, Any],
    *,
    snapshot_path: Path,
    expected_names: set[str],
    source_id: str,
    profile: dict[str, Any],
    report: CorpusReport,
) -> None:
    adapter = source.get("adapter")
    if not isinstance(adapter, str) or not adapter:
        report.issues.append(
            _issue(
                "source_adapter_missing",
                "Ingest verification requires a stable adapter name.",
                source_id=source_id,
            )
        )
        return
    try:
        document = json.loads(snapshot_path.read_text(encoding="utf-8"))
        ingest_options = source.get("ingest_options") or {}
        if not isinstance(ingest_options, dict):
            raise TypeError("ingest_options must be an object")
        result = ingest_source(
            document,
            format_hint=adapter,
            strict=False,
            **ingest_options,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        report.issues.append(
            _issue(
                "source_ingest_failed",
                f"Source could not be ingested with its declared adapter: {exc}",
                source_id=source_id,
            )
        )
        return

    tool_names = {tool.name for tool in result.tools}
    profile["adapter"] = result.adapter
    profile["tool_count"] = len(tool_names)
    profile["ingest_ready"] = result.ready
    profile["ingest_issue_codes"] = [issue.code for issue in result.issues]
    expected_tool_count = source.get("expected_tool_count")
    if not isinstance(expected_tool_count, int) or expected_tool_count < 1:
        report.issues.append(
            _issue(
                "source_expected_tool_count_missing",
                "Every ingest-verified source must declare expected_tool_count.",
                source_id=source_id,
            )
        )
    elif len(tool_names) != expected_tool_count:
        report.issues.append(
            _issue(
                "source_tool_count_mismatch",
                "Ingested tool count differs from the frozen manifest.",
                source_id=source_id,
                evidence={"expected": expected_tool_count, "actual": len(tool_names)},
            )
        )
    missing = sorted(expected_names - tool_names)
    if missing:
        report.issues.append(
            _issue(
                "ground_truth_tool_missing",
                "Ground truth references tools absent from the ingested snapshot.",
                source_id=source_id,
                evidence={"missing": missing},
            )
        )
    blockers = [issue.code for issue in result.issues if issue.severity == "blocker"]
    if blockers:
        report.issues.append(
            _issue(
                "source_ingest_blocked",
                "Declared ingest options must produce an execution-ready source.",
                source_id=source_id,
                evidence={"issue_codes": blockers},
            )
        )


def _validate_paper_readiness(
    manifest: dict[str, Any],
    *,
    report: CorpusReport,
    family_splits: dict[str, set[str]],
    source_type_families: dict[str, set[str]],
) -> None:
    policy = manifest.get("paper_readiness_policy")
    if not isinstance(policy, dict):
        report.issues.append(
            _issue(
                "paper_readiness_policy_missing",
                "Manifest must define measurable paper-readiness thresholds.",
                scope="paper_readiness",
            )
        )
        return
    required_source_types = set(policy.get("required_source_types") or [])
    missing_source_types = sorted(required_source_types - set(report.paper_core_source_type_counts))
    if missing_source_types:
        report.issues.append(
            _issue(
                "paper_source_types_missing",
                "Paper corpus does not yet cover every required source type.",
                scope="paper_readiness",
                evidence={"missing": missing_source_types},
            )
        )
    required_splits = set(policy.get("required_splits") or [])
    populated_splits = {
        split for split, count in report.paper_core_split_query_counts.items() if count
    }
    missing_splits = sorted(required_splits - populated_splits)
    if missing_splits:
        report.issues.append(
            _issue(
                "paper_splits_missing",
                "Paper corpus does not yet populate every required split.",
                scope="paper_readiness",
                evidence={"missing": missing_splits},
            )
        )
    minimum_families = int(policy.get("min_families_per_source_type") or 1)
    weak_types = {
        source_type: len(source_type_families.get(source_type, set()))
        for source_type in sorted(required_source_types)
        if len(source_type_families.get(source_type, set())) < minimum_families
    }
    if weak_types:
        report.issues.append(
            _issue(
                "paper_source_family_coverage_insufficient",
                "Each source type needs independent API families for held-out evaluation.",
                scope="paper_readiness",
                evidence={"required": minimum_families, "actual": weak_types},
            )
        )
    minimum_queries = int(policy.get("min_queries_per_split") or 1)
    weak_splits = {
        split: report.paper_core_split_query_counts.get(split, 0)
        for split in sorted(required_splits)
        if report.paper_core_split_query_counts.get(split, 0) < minimum_queries
    }
    if weak_splits:
        report.issues.append(
            _issue(
                "paper_split_query_coverage_insufficient",
                "Each split needs enough independently annotated queries.",
                scope="paper_readiness",
                evidence={"required": minimum_queries, "actual": weak_splits},
            )
        )
    minimum_reviewers = int(policy.get("min_annotation_reviewers") or 1)
    weak_review_sources = {
        str(profile.get("source_id") or ""): len(profile.get("annotation_reviewers") or [])
        for profile in report.source_profiles
        if profile.get("paper_core")
        and len(profile.get("annotation_reviewers") or []) < minimum_reviewers
    }
    if weak_review_sources:
        report.issues.append(
            _issue(
                "paper_annotation_review_coverage_insufficient",
                "Paper annotations require independent human review before test evaluation.",
                scope="paper_readiness",
                evidence={"required": minimum_reviewers, "actual": weak_review_sources},
            )
        )
    if report.paper_core_source_count != report.source_count:
        report.issues.append(
            CorpusIssue(
                severity="warning",
                code="paper_non_core_sources_present",
                message="Non-core sources are excluded from primary paper claims.",
                scope="paper_readiness",
                evidence={
                    "paper_core": report.paper_core_source_count,
                    "all_sources": report.source_count,
                },
            )
        )
    if not family_splits:
        report.issues.append(
            _issue(
                "paper_families_missing",
                "Paper corpus requires API-family partitions.",
                scope="paper_readiness",
            )
        )


def _repository_root(
    manifest_path: Path,
    manifest: dict[str, Any],
    report: CorpusReport,
) -> Path:
    value = manifest.get("repository_root")
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        report.issues.append(
            _issue(
                "repository_root_invalid",
                "repository_root must be an explicit non-empty relative path.",
            )
        )
        return manifest_path.parent
    return (manifest_path.parent / value).resolve()


def _resolve_artifact_path(
    value: Any,
    *,
    field_name: str,
    manifest_path: Path,
    repository_root: Path,
    source_id: str,
    report: CorpusReport,
) -> Path | None:
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        report.issues.append(
            _issue(
                f"source_{field_name}_invalid",
                f"{field_name} must be a non-empty path relative to the manifest.",
                source_id=source_id,
            )
        )
        return None
    resolved = (manifest_path.parent / value).resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        report.issues.append(
            _issue(
                "source_path_escape",
                "Corpus artifacts must stay inside repository_root.",
                source_id=source_id,
                evidence={"field": field_name},
            )
        )
        return None
    if not resolved.is_file():
        report.issues.append(
            _issue(
                f"source_{field_name}_missing",
                f"Referenced {field_name} file does not exist.",
                source_id=source_id,
                evidence={"path": str(resolved)},
            )
        )
        return None
    return resolved


def _validate_file_fingerprint(
    path: Path,
    *,
    expected_sha256: Any,
    expected_bytes: Any,
    verify_hashes: bool,
    source_id: str,
    code_prefix: str,
    report: CorpusReport,
) -> None:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        report.issues.append(
            _issue(
                f"{code_prefix}_sha256_invalid",
                f"{code_prefix} must declare a 64-character SHA-256 digest.",
                source_id=source_id,
            )
        )
    elif verify_hashes:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            report.issues.append(
                _issue(
                    f"{code_prefix}_sha256_mismatch",
                    f"{code_prefix} SHA-256 does not match the frozen manifest.",
                    source_id=source_id,
                    evidence={"expected": expected_sha256, "actual": actual},
                )
            )
    if expected_bytes is not None:
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            report.issues.append(
                _issue(
                    f"{code_prefix}_bytes_invalid",
                    f"{code_prefix} bytes must be a non-negative integer.",
                    source_id=source_id,
                )
            )
        elif path.stat().st_size != expected_bytes:
            report.issues.append(
                _issue(
                    f"{code_prefix}_bytes_mismatch",
                    f"{code_prefix} byte size does not match the frozen manifest.",
                    source_id=source_id,
                    evidence={"expected": expected_bytes, "actual": path.stat().st_size},
                )
            )


def _required_string(value: Any, field_name: str, report: CorpusReport) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    report.issues.append(
        _issue(
            f"manifest_{field_name}_missing",
            f"Corpus manifest must define {field_name}.",
        )
    )
    return ""


def _source_string(
    source: dict[str, Any],
    field_name: str,
    report: CorpusReport,
    *,
    source_id: str = "",
) -> str:
    value = source.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    report.issues.append(
        _issue(
            f"source_{field_name}_missing",
            f"Corpus source must define {field_name}.",
            source_id=source_id or None,
        )
    )
    return ""


def _issue(
    code: str,
    message: str,
    *,
    scope: str = "integrity",
    source_id: str | None = None,
    case_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> CorpusIssue:
    return CorpusIssue(
        severity="blocker",
        code=code,
        message=message,
        scope=scope,
        source_id=source_id,
        case_id=case_id,
        evidence=evidence or {},
    )


def _complete_split_counts(counts: Counter[str]) -> dict[str, int]:
    return {split: int(counts.get(split, 0)) for split in sorted(ALLOWED_SPLITS)}


def format_corpus_report(report: CorpusReport) -> str:
    """Format a compact human-readable corpus status."""
    lines = [
        (
            "paper-corpus integrity={integrity} paper_ready={paper} "
            "sources={sources} families={families} queries={queries}"
        ).format(
            integrity="pass" if report.integrity_ready else "fail",
            paper="pass" if report.paper_ready else "fail",
            sources=report.source_count,
            families=report.family_count,
            queries=report.query_count,
        ),
        f"source_types={report.source_type_counts}",
        f"paper_core_source_types={report.paper_core_source_type_counts}",
        (
            f"held_out_sources={report.held_out_source_count} "
            f"annotation_reviewers={report.annotation_reviewer_count}"
        ),
        f"split_sources={report.split_source_counts}",
        f"split_queries={report.split_query_counts}",
        f"paper_core_split_queries={report.paper_core_split_query_counts}",
    ]
    for issue in report.issues:
        lines.append(
            "[{scope}:{severity}] {code}{source}: {message}".format(
                scope=issue.scope,
                severity=issue.severity,
                code=issue.code,
                source=f" source={issue.source_id}" if issue.source_id else "",
                message=issue.message,
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Inspect structure only. Never use this mode for CI or paper claims.",
    )
    parser.add_argument("--verify-ingest", action="store_true")
    parser.add_argument("--require-paper-ready", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.epilog = (
        "Exit codes: 0 integrity passed; 1 integrity failed; "
        "2 --require-paper-ready was requested but the paper gate failed."
    )
    args = parser.parse_args(argv)

    report = validate_corpus_manifest(
        args.manifest,
        verify_hashes=not args.no_verify_hashes,
        verify_ingest=args.verify_ingest,
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_corpus_report(report))
    if not report.integrity_ready:
        return 1
    if args.require_paper_ready and not report.paper_ready:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
