"""Check BFCL sweep milestone gates from saved artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.bfcl_tool_selection.sweep import (
    DEFAULT_MILESTONE_PROFILE,
    MILESTONE_PROFILES,
    _evaluate_milestone_gate,
    _format_milestone_gate,
)


def load_gate(
    report_path: Path,
    *,
    profile: str = DEFAULT_MILESTONE_PROFILE,
) -> dict[str, Any]:
    """Load or recompute a BFCL milestone gate from a sweep artifact."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary") or {}
    gate = summary.get("milestone_gate") or {}
    if gate and gate.get("profile") == profile:
        return gate

    rows = summary.get("rows") or []
    category_rows = summary.get("category_rows") or []
    return _evaluate_milestone_gate(rows, category_rows, profile_name=profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="BFCL sweep JSON artifact to check.")
    parser.add_argument(
        "--profile",
        choices=[*MILESTONE_PROFILES.keys()],
        default=DEFAULT_MILESTONE_PROFILE,
        help="Milestone gate profile to evaluate.",
    )
    parser.add_argument("--json", action="store_true", help="Print the gate as JSON.")
    args = parser.parse_args(argv)

    gate = load_gate(args.report, profile=args.profile)
    if args.json:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
    else:
        print(_format_milestone_gate(gate))
    return 0 if gate.get("status") == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
