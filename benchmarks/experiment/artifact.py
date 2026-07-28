"""Versioned experiment artifact schema and provenance helpers."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_tool_call import __version__

SCHEMA_VERSION = 1
ALLOWED_RUN_KINDS = frozenset({"deterministic", "execution", "model", "xgen"})
ALLOWED_STATUSES = frozenset({"completed", "failed", "partial"})
ALLOWED_SPLITS = frozenset({"dev", "mixed", "test", "train", "unspecified"})


@dataclass(frozen=True)
class ExperimentIssue:
    code: str
    message: str
    path: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentValidationReport:
    artifact_path: str = ""
    artifact_id: str = ""
    run_id: str = ""
    case_count: int = 0
    issues: list[ExperimentIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "case_count": self.case_count,
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class ExperimentArtifact:
    """One normalized experiment result with complete run provenance."""

    benchmark: str
    methodology: str
    run_kind: str
    created_at: str
    status: str = "completed"
    seed: int = 0
    schema_version: int = SCHEMA_VERSION
    run_id: str = ""
    artifact_id: str = ""
    dataset: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    tokenizer: dict[str, Any] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExperimentArtifact:
        fields = {
            "benchmark",
            "methodology",
            "run_kind",
            "created_at",
            "status",
            "seed",
            "schema_version",
            "run_id",
            "artifact_id",
            "dataset",
            "config",
            "provenance",
            "model",
            "tokenizer",
            "replay",
            "summary",
            "statistics",
            "cases",
            "source",
        }
        return cls(**{key: value[key] for key in fields if key in value})


def collect_runtime_provenance(repository_root: str | Path | None = None) -> dict[str, Any]:
    """Collect stable software provenance without environment values or secrets."""
    root = Path(repository_root or Path(__file__).resolve().parents[2]).resolve()
    lock_path = _first_existing(root / "poetry.lock", root / "uv.lock")
    return {
        "graph_tool_call_version": __version__,
        "git_commit": _git(root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git(root, "status", "--porcelain")),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "dependency_lock_path": lock_path.name if lock_path else "",
        "dependency_lock_sha256": _sha256(lock_path) if lock_path else "",
    }


def finalize_artifact(
    artifact: ExperimentArtifact,
    *,
    repository_root: str | Path | None = None,
) -> ExperimentArtifact:
    """Fill provenance and deterministic identifiers in-place."""
    if not artifact.created_at:
        artifact.created_at = datetime.now(timezone.utc).isoformat()
    if not artifact.provenance:
        artifact.provenance = collect_runtime_provenance(repository_root)
    artifact.run_id = compute_run_id(artifact)
    artifact.artifact_id = compute_artifact_id(artifact)
    return artifact


def compute_run_id(artifact: ExperimentArtifact | dict[str, Any]) -> str:
    """Return a deterministic ID for the frozen run configuration."""
    value = _as_dict(artifact)
    identity = {
        "schema_version": value.get("schema_version"),
        "benchmark": value.get("benchmark"),
        "methodology": value.get("methodology"),
        "run_kind": value.get("run_kind"),
        "seed": value.get("seed"),
        "dataset": value.get("dataset"),
        "config": value.get("config"),
        "model": value.get("model"),
        "tokenizer": value.get("tokenizer"),
        "replay": value.get("replay"),
        "software": {
            key: (value.get("provenance") or {}).get(key)
            for key in (
                "dependency_lock_sha256",
                "git_commit",
                "graph_tool_call_version",
                "python_version",
            )
        },
    }
    return f"run-{_digest(identity)[:20]}"


def compute_artifact_id(artifact: ExperimentArtifact | dict[str, Any]) -> str:
    """Return a content ID for an exact artifact payload."""
    value = _as_dict(artifact)
    value.pop("artifact_id", None)
    return f"exp-{_digest(value)[:24]}"


def validate_artifact(
    artifact: ExperimentArtifact | dict[str, Any],
    *,
    artifact_path: str = "",
) -> ExperimentValidationReport:
    """Validate schema, identity hashes, provenance, and case uniqueness."""
    value = _as_dict(artifact)
    report = ExperimentValidationReport(
        artifact_path=artifact_path,
        artifact_id=str(value.get("artifact_id") or ""),
        run_id=str(value.get("run_id") or ""),
    )
    if value.get("schema_version") != SCHEMA_VERSION:
        _issue(report, "experiment_schema_version_unsupported", "schema_version must be 1.")
    for key in ("benchmark", "methodology", "created_at"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            _issue(report, f"experiment_{key}_missing", f"{key} must be a non-empty string.")
    if isinstance(value.get("created_at"), str) and value["created_at"].strip():
        try:
            datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
        except ValueError:
            _issue(
                report,
                "experiment_created_at_invalid",
                "created_at must be an ISO-8601 timestamp.",
            )
    if value.get("run_kind") not in ALLOWED_RUN_KINDS:
        _issue(
            report,
            "experiment_run_kind_invalid",
            "run_kind is outside the frozen taxonomy.",
            evidence={"allowed": sorted(ALLOWED_RUN_KINDS), "actual": value.get("run_kind")},
        )
    if value.get("status") not in ALLOWED_STATUSES:
        _issue(
            report,
            "experiment_status_invalid",
            "status is outside the frozen taxonomy.",
            evidence={"allowed": sorted(ALLOWED_STATUSES), "actual": value.get("status")},
        )
    if not isinstance(value.get("seed"), int) or isinstance(value.get("seed"), bool):
        _issue(report, "experiment_seed_invalid", "seed must be an integer.")

    dataset = value.get("dataset")
    if not isinstance(dataset, dict):
        _issue(report, "experiment_dataset_invalid", "dataset must be an object.")
        dataset = {}
    if dataset.get("split", "unspecified") not in ALLOWED_SPLITS:
        _issue(
            report,
            "experiment_dataset_split_invalid",
            "dataset.split is outside the frozen taxonomy.",
            path="dataset.split",
            evidence={"allowed": sorted(ALLOWED_SPLITS), "actual": dataset.get("split")},
        )
    if not isinstance(dataset.get("id"), str) or not dataset.get("id", "").strip():
        _issue(
            report,
            "experiment_dataset_id_missing",
            "dataset.id must be set.",
            path="dataset.id",
        )
    dataset_fingerprints = (
        dataset.get("manifest_sha256"),
        dataset.get("source_sha256"),
        dataset.get("source_hashes"),
    )
    if not any(fingerprint for fingerprint in dataset_fingerprints):
        _issue(
            report,
            "experiment_dataset_fingerprint_missing",
            "dataset must record a manifest or source fingerprint.",
            path="dataset",
        )

    provenance = value.get("provenance")
    if not isinstance(provenance, dict):
        _issue(report, "experiment_provenance_invalid", "provenance must be an object.")
        provenance = {}
    for key in (
        "dependency_lock_sha256",
        "git_commit",
        "graph_tool_call_version",
        "python_version",
    ):
        if not isinstance(provenance.get(key), str) or not provenance[key].strip():
            _issue(
                report,
                f"experiment_provenance_{key}_missing",
                f"provenance.{key} must be set.",
                path=f"provenance.{key}",
            )

    tokenizer = value.get("tokenizer")
    if not isinstance(tokenizer, dict):
        _issue(report, "experiment_tokenizer_invalid", "tokenizer must be an object.")
    elif tokenizer:
        for key in ("name", "revision"):
            if not isinstance(tokenizer.get(key), str) or not tokenizer[key].strip():
                _issue(
                    report,
                    f"experiment_tokenizer_{key}_missing",
                    f"tokenizer.{key} is required when tokenizer metadata is present.",
                    path=f"tokenizer.{key}",
                )

    model = value.get("model")
    if not isinstance(model, dict):
        _issue(report, "experiment_model_invalid", "model must be an object.")
    elif value.get("run_kind") == "model":
        for key in ("name", "provider", "revision"):
            if not isinstance(model.get(key), str) or not model[key].strip():
                _issue(
                    report,
                    f"experiment_model_{key}_missing",
                    f"model.{key} is required for model runs.",
                    path=f"model.{key}",
                )

    replay = value.get("replay")
    if not isinstance(replay, dict):
        _issue(report, "experiment_replay_invalid", "replay must be an object.")
    else:
        command = replay.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            _issue(
                report,
                "experiment_replay_command_missing",
                "replay.command must be a non-empty argument list.",
                path="replay.command",
            )
        if not isinstance(replay.get("working_directory"), str):
            _issue(
                report,
                "experiment_replay_working_directory_invalid",
                "replay.working_directory must be a string.",
                path="replay.working_directory",
            )

    source = value.get("source")
    if not isinstance(source, dict):
        _issue(report, "experiment_source_invalid", "source must be an object.")
    else:
        for key in ("type", "sha256"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                _issue(
                    report,
                    f"experiment_source_{key}_missing",
                    f"source.{key} must be set.",
                    path=f"source.{key}",
                )

    cases = value.get("cases")
    if not isinstance(cases, list):
        _issue(report, "experiment_cases_invalid", "cases must be a list.")
        cases = []
    report.case_count = len(cases)
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            _issue(
                report,
                "experiment_case_invalid",
                "Every case must be an object.",
                path=f"cases[{index}]",
            )
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            _issue(
                report,
                "experiment_case_id_missing",
                "Every case must have a stable case_id.",
                path=f"cases[{index}].case_id",
            )
        elif case_id in seen:
            _issue(
                report,
                "experiment_case_id_duplicate",
                "Case IDs must be unique within an artifact.",
                path=f"cases[{index}].case_id",
                evidence={"case_id": case_id},
            )
        else:
            seen.add(case_id)

    expected_run_id = compute_run_id(value)
    if value.get("run_id") != expected_run_id:
        _issue(
            report,
            "experiment_run_id_mismatch",
            "run_id does not match the frozen run configuration.",
            evidence={"expected": expected_run_id, "actual": value.get("run_id")},
        )
    expected_artifact_id = compute_artifact_id(value)
    if value.get("artifact_id") != expected_artifact_id:
        _issue(
            report,
            "experiment_artifact_id_mismatch",
            "artifact_id does not match the artifact content.",
            evidence={"expected": expected_artifact_id, "actual": value.get("artifact_id")},
        )
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        _issue(
            report,
            "experiment_json_serialization_failed",
            f"Artifact must contain only stable JSON values: {exc}",
        )
    return report


def load_artifact(path: str | Path) -> ExperimentArtifact:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Experiment artifact root must be an object.")
    return ExperimentArtifact.from_dict(value)


def write_artifact(path: str | Path, artifact: ExperimentArtifact) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _as_dict(value: ExperimentArtifact | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, ExperimentArtifact):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    raise TypeError("artifact must be an ExperimentArtifact or dict")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _first_existing(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _issue(
    report: ExperimentValidationReport,
    code: str,
    message: str,
    *,
    path: str = "",
    evidence: dict[str, Any] | None = None,
) -> None:
    report.issues.append(
        ExperimentIssue(code=code, message=message, path=path, evidence=evidence or {})
    )
