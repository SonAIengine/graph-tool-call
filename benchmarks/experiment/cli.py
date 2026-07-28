"""Create, validate, inspect, and describe replay for experiment artifacts."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

from benchmarks.experiment.adapters import ALLOWED_SOURCE_TYPES, adapt_legacy_report
from benchmarks.experiment.artifact import load_artifact, validate_artifact, write_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Adapt a legacy benchmark JSON report.")
    create.add_argument("source", type=Path)
    create.add_argument("--source-type", choices=sorted(ALLOWED_SOURCE_TYPES), required=True)
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--benchmark")
    create.add_argument("--methodology")
    create.add_argument("--run-kind", choices=["deterministic", "execution", "model", "xgen"])
    create.add_argument("--seed", type=int, default=0)
    create.add_argument("--dataset-id", required=True)
    create.add_argument(
        "--split",
        choices=["train", "dev", "test", "mixed", "unspecified"],
        default="unspecified",
    )
    create.add_argument("--model-name")
    create.add_argument("--model-provider")
    create.add_argument("--model-revision")
    create.add_argument("--tokenizer-name")
    create.add_argument("--tokenizer-revision")
    create.add_argument("--replay-command", nargs=argparse.REMAINDER)

    validate = commands.add_parser("validate", help="Validate one experiment artifact.")
    validate.add_argument("artifact", type=Path)
    validate.add_argument("--json", action="store_true")

    inspect = commands.add_parser("inspect", help="Print high-signal artifact metadata.")
    inspect.add_argument("artifact", type=Path)
    inspect.add_argument("--json", action="store_true")

    replay = commands.add_parser(
        "replay",
        help="Print the frozen replay command. This command never executes it.",
    )
    replay.add_argument("artifact", type=Path)

    args = parser.parse_args(argv)
    if args.command == "create":
        return _create(args)
    if args.command == "validate":
        return _validate(args)
    if args.command == "inspect":
        return _inspect(args)
    return _replay(args)


def _create(args: argparse.Namespace) -> int:
    report = _load_json(args.source)
    model = _optional_named_metadata(
        args.model_name,
        provider=args.model_provider,
        revision=args.model_revision,
    )
    tokenizer = _optional_named_metadata(args.tokenizer_name, revision=args.tokenizer_revision)
    artifact = adapt_legacy_report(
        report,
        source_type=args.source_type,
        benchmark=args.benchmark,
        methodology=args.methodology,
        run_kind=args.run_kind,
        seed=args.seed,
        dataset={
            "id": args.dataset_id,
            "split": args.split,
            "source_path": str(args.source),
            "source_sha256": _sha256(args.source),
        },
        model=model,
        tokenizer=tokenizer,
        replay_command=args.replay_command,
    )
    validation = validate_artifact(artifact)
    if not validation.valid:
        print(json.dumps(validation.to_dict(), ensure_ascii=False, indent=2))
        return 1
    write_artifact(args.out, artifact)
    print(args.out)
    return 0


def _validate(args: argparse.Namespace) -> int:
    artifact = load_artifact(args.artifact)
    report = validate_artifact(artifact, artifact_path=str(args.artifact))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_format_validation(report))
    return 0 if report.valid else 1


def _inspect(args: argparse.Namespace) -> int:
    artifact = load_artifact(args.artifact)
    report = validate_artifact(artifact, artifact_path=str(args.artifact))
    summary = {
        "valid": report.valid,
        "artifact_id": artifact.artifact_id,
        "run_id": artifact.run_id,
        "benchmark": artifact.benchmark,
        "methodology": artifact.methodology,
        "run_kind": artifact.run_kind,
        "status": artifact.status,
        "seed": artifact.seed,
        "dataset": artifact.dataset,
        "model": artifact.model,
        "tokenizer": artifact.tokenizer,
        "case_count": len(artifact.cases),
        "source": artifact.source,
        "issues": [issue.to_dict() for issue in report.issues],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0 if report.valid else 1


def _replay(args: argparse.Namespace) -> int:
    artifact = load_artifact(args.artifact)
    report = validate_artifact(artifact, artifact_path=str(args.artifact))
    if not report.valid:
        print(_format_validation(report))
        return 1
    command = artifact.replay.get("command") or []
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        print("replay command is invalid")
        return 1
    if not command:
        print("replay command is not recorded")
        return 2
    print(shlex.join(command))
    return 0


def _optional_named_metadata(
    name: str | None,
    *,
    provider: str | None = None,
    revision: str | None = None,
) -> dict[str, str]:
    if not name:
        return {}
    value = {"name": name, "revision": revision or "unrecorded"}
    if provider is not None:
        value["provider"] = provider or "unrecorded"
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Legacy benchmark report root must be an object.")
    return value


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _format_validation(report: Any) -> str:
    lines = [
        f"valid={'pass' if report.valid else 'fail'}",
        f"artifact_id={report.artifact_id}",
        f"run_id={report.run_id}",
        f"cases={report.case_count}",
    ]
    lines.extend(f"[error] {issue.code}: {issue.message}" for issue in report.issues)
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
