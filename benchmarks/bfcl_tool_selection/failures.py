"""Extract reusable BFCL failure subsets from benchmark report JSON.

The full model-in-the-loop benchmark is expensive. This helper turns an
existing full report into a small case-id file, so search/reranking changes can
be validated against the exact failures they are intended to fix.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def extract_failure_cases(
    report: dict[str, Any],
    *,
    failure_categories: set[str] | None = None,
    categories: set[str] | None = None,
    tool_sources: set[str] | None = None,
    top_ks: set[int] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return unique failing cases matching the requested report filters."""
    selected: dict[str, dict[str, Any]] = {}
    for run in _iter_reports(report):
        run_tool_source = str(
            run.get("tool_source") or run.get("report", {}).get("tool_source") or ""
        )
        run_top_k = _coerce_int(run.get("top_k") or run.get("report", {}).get("top_k"))
        if tool_sources is not None and run_tool_source not in tool_sources:
            continue
        if top_ks is not None and run_top_k not in top_ks:
            continue

        nested_report = run.get("report") if isinstance(run.get("report"), dict) else run
        for category in nested_report.get("categories") or []:
            category_name = str(category.get("category") or "")
            if categories is not None and category_name not in categories:
                continue
            for case in category.get("cases") or []:
                failure = str(case.get("failure_category") or "")
                if not failure or failure == "pass":
                    continue
                if failure_categories is not None and failure not in failure_categories:
                    continue
                case_id = str(case.get("case_id") or case.get("id") or "")
                if not case_id or case_id in selected:
                    continue
                selected[case_id] = {
                    "case_id": case_id,
                    "category": category_name,
                    "failure_category": failure,
                    "tool_source": run_tool_source,
                    "top_k": run_top_k,
                    "retrieval_recall_at_k": case.get("retrieval_recall_at_k"),
                    "evaluator_exact_match": case.get("evaluator_exact_match"),
                }
                if limit is not None and len(selected) >= max(0, limit):
                    return list(selected.values())
    return list(selected.values())


def _iter_reports(report: dict[str, Any]) -> list[dict[str, Any]]:
    runs = report.get("runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, dict)]
    return [report]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_strings(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def _parse_ints(value: str | None) -> set[int] | None:
    if not value:
        return None
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def _write_output(rows: list[dict[str, Any]], output: Path | None, *, json_output: bool) -> None:
    if json_output:
        text = json.dumps({"case_ids": [row["case_id"] for row in rows], "cases": rows}, indent=2)
    else:
        text = "\n".join(row["case_id"] for row in rows)
        if text:
            text += "\n"

    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="BFCL llm_loop or sweep JSON")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--failure-categories",
        default="retrieval_miss,candidate_ambiguity",
        help="Comma-separated failure categories to extract. Empty means all non-pass failures.",
    )
    parser.add_argument("--categories", default="", help="Comma-separated BFCL categories")
    parser.add_argument("--tool-sources", default="", help="Comma-separated tool sources")
    parser.add_argument("--top-ks", default="", help="Comma-separated top-K values")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Write JSON instead of plain case IDs")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    rows = extract_failure_cases(
        report,
        failure_categories=_parse_strings(args.failure_categories),
        categories=_parse_strings(args.categories),
        tool_sources=_parse_strings(args.tool_sources),
        top_ks=_parse_ints(args.top_ks),
        limit=args.limit,
    )
    _write_output(rows, args.output, json_output=args.json)
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
