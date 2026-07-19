"""Build reusable BFCL hard-case bundles from an expensive benchmark report.

This module combines the existing failure extractor and deterministic failure
inspector into one artifact directory. It is meant for the fast research loop:
run a full or smoke benchmark once, freeze the hard cases, then iterate on the
small subset without re-running the expensive model path.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.bfcl_tool_selection.failures import extract_failure_cases
from benchmarks.bfcl_tool_selection.inspect import inspect_failures
from benchmarks.bfcl_tool_selection.run import BFCL_REF, load_case_ids
from graph_tool_call import __version__


def build_hard_case_bundle(
    *,
    report: dict[str, Any],
    categories: list[str] | None = None,
    data_root: Path | None = None,
    ref: str = BFCL_REF,
    top_k: int = 5,
    inspect_depth: int = 20,
    failure_categories: set[str] | None = None,
    tool_sources: set[str] | None = None,
    top_ks: set[int] | None = None,
    case_ids: set[str] | None = None,
    limit: int | None = None,
    max_distractors: int = 5,
) -> dict[str, Any]:
    """Return a frozen hard-case bundle with deterministic inspection evidence."""
    category_filter = set(categories) if categories else None
    rows = extract_failure_cases(
        report,
        failure_categories=failure_categories,
        categories=category_filter,
        tool_sources=tool_sources,
        top_ks=top_ks,
        limit=limit,
    )
    if case_ids is not None:
        rows = [row for row in rows if str(row.get("case_id")) in case_ids]
    selected_case_ids = {str(row["case_id"]) for row in rows}
    inspection = inspect_failures(
        report=report,
        categories=categories,
        data_root=data_root,
        ref=ref,
        top_k=top_k,
        inspect_depth=inspect_depth,
        case_ids=selected_case_ids,
        failure_categories=failure_categories,
        tool_sources=tool_sources,
        top_ks=top_ks,
        limit=limit,
        max_distractors=max_distractors,
    )
    return {
        "benchmark": "BFCL v4 Hard Case Bundle",
        "methodology": "bfcl_hard_case_bundle",
        "graph_tool_call_version": __version__,
        "model": _report_model(report),
        "bfcl_ref": ref,
        "source": "local" if data_root else "official_gorilla_repo",
        "filters": {
            "categories": categories or [],
            "failure_categories": sorted(failure_categories or []),
            "tool_sources": sorted(tool_sources or []),
            "top_ks": sorted(top_ks or []),
            "case_ids": sorted(case_ids or []),
            "limit": limit,
            "top_k": top_k,
            "inspect_depth": max(top_k, inspect_depth),
        },
        "summary": _summarize(rows, inspection),
        "case_ids": [str(row["case_id"]) for row in rows],
        "failure_cases": rows,
        "inspection": inspection,
    }


def write_hard_case_bundle(bundle: dict[str, Any], out_dir: Path) -> dict[str, str]:
    """Write bundle JSON plus reusable case-id files and return created paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "bundle": out_dir / "bundle.json",
        "cases": out_dir / "cases.json",
        "case_ids": out_dir / "case_ids.txt",
        "inspect": out_dir / "inspect.json",
        "summary": out_dir / "summary.json",
    }
    paths["bundle"].write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["cases"].write_text(
        json.dumps(
            {"case_ids": bundle["case_ids"], "cases": bundle["failure_cases"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_case_ids(paths["case_ids"], bundle["case_ids"])
    paths["inspect"].write_text(
        json.dumps(bundle["inspection"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["summary"].write_text(
        json.dumps(bundle["summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    extra_paths = _write_grouped_case_ids(bundle, out_dir)
    return {key: str(path) for key, path in {**paths, **extra_paths}.items()}


def _write_grouped_case_ids(bundle: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    failure_groups: dict[str, list[str]] = {}
    for row in bundle["failure_cases"]:
        failure = str(row.get("failure_category") or "unknown")
        failure_groups.setdefault(failure, []).append(str(row["case_id"]))
    for failure, ids in sorted(failure_groups.items()):
        path = out_dir / f"failure_{_slug(failure)}.txt"
        _write_case_ids(path, ids)
        paths[f"failure_{failure}"] = path

    tag_groups: dict[str, list[str]] = {}
    for row in bundle["failure_cases"]:
        case_id = str(row.get("case_id") or "")
        if not case_id:
            continue
        for tag in row.get("failure_tags") or []:
            tag_groups.setdefault(str(tag), []).append(case_id)
    for tag, ids in sorted(tag_groups.items()):
        path = out_dir / f"tag_{_slug(tag)}.txt"
        _write_case_ids(path, ids)
        paths[f"tag_{tag}"] = path

    issue_groups: dict[str, list[str]] = {}
    for case in bundle["inspection"].get("cases") or []:
        case_id = str(case.get("case_id") or "")
        if not case_id:
            continue
        for issue in case.get("issues") or []:
            issue_groups.setdefault(str(issue), []).append(case_id)
    for issue, ids in sorted(issue_groups.items()):
        path = out_dir / f"issue_{_slug(issue)}.txt"
        _write_case_ids(path, ids)
        paths[f"issue_{issue}"] = path
    return paths


def _write_case_ids(path: Path, case_ids: list[str]) -> None:
    text = "\n".join(case_ids)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _summarize(rows: list[dict[str, Any]], inspection: dict[str, Any]) -> dict[str, Any]:
    failures = Counter(str(row.get("failure_category") or "unknown") for row in rows)
    failure_tags = Counter(str(tag) for row in rows for tag in row.get("failure_tags") or [])
    categories = Counter(str(row.get("category") or "unknown") for row in rows)
    inspect_summary = inspection.get("summary") or {}
    issue_counts = Counter(inspect_summary.get("issues") or {})
    inspected_cases = inspection.get("cases") or []
    near_miss_cases = sum(
        1 for case in inspected_cases if "expected_present_below_top_k" in case.get("issues", [])
    )
    partial_multi_cases = sum(
        1 for case in inspected_cases if "partial_multi_tool_at_k" in case.get("issues", [])
    )
    weak_keyword_cases = sum(
        1 for case in inspected_cases if "weak_or_missing_keyword_signal" in case.get("issues", [])
    )
    outside_depth_cases = sum(1 for case in inspected_cases if case.get("missing_at_depth"))
    return {
        "cases": len(rows),
        "inspected_cases": len(inspected_cases),
        "failure_categories": dict(sorted(failures.items())),
        "failure_tags": dict(sorted(failure_tags.items())),
        "categories": dict(sorted(categories.items())),
        "issues": dict(issue_counts.most_common()),
        "near_miss_case_count": near_miss_cases,
        "partial_multi_tool_case_count": partial_multi_cases,
        "weak_keyword_case_count": weak_keyword_cases,
        "outside_inspect_depth_case_count": outside_depth_cases,
        "missing_tool_mentions_at_k": inspect_summary.get("missing_tool_mentions_at_k", 0),
        "missing_tool_mentions_at_depth": inspect_summary.get("missing_tool_mentions_at_depth", 0),
        "rank_buckets": inspect_summary.get("rank_buckets", {}),
    }


def _report_model(report: dict[str, Any]) -> str:
    model = report.get("model")
    if model:
        return str(model)
    for run in report.get("runs") or []:
        if isinstance(run, dict) and run.get("model"):
            return str(run["model"])
        nested = run.get("report") if isinstance(run, dict) else None
        if isinstance(nested, dict) and nested.get("model"):
            return str(nested["model"])
    return "unknown"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return slug.strip("._") or "unknown"


def _parse_strings(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def _parse_ints(value: str | None) -> set[int] | None:
    if not value:
        return None
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def _parse_categories(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def print_report(bundle: dict[str, Any], *, paths: dict[str, str] | None = None) -> None:
    """Print a compact terminal summary."""
    summary = bundle["summary"]
    print(bundle["benchmark"])
    print(
        "cases={cases} inspected={inspected} near_miss={near} partial_multi={partial} "
        "weak_keyword={weak} outside_depth={outside}".format(
            cases=summary["cases"],
            inspected=summary["inspected_cases"],
            near=summary["near_miss_case_count"],
            partial=summary["partial_multi_tool_case_count"],
            weak=summary["weak_keyword_case_count"],
            outside=summary["outside_inspect_depth_case_count"],
        )
    )
    print(f"failure_categories={summary['failure_categories']}")
    if summary["failure_tags"]:
        print(f"failure_tags={summary['failure_tags']}")
    print(f"issues={summary['issues']}")
    if paths:
        print(f"out_dir={Path(paths['bundle']).parent}")
        print(f"case_ids={paths['case_ids']}")
        print(f"inspect={paths['inspect']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/gtc-bfcl-hard-cases"))
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--ref", default=BFCL_REF)
    parser.add_argument("--categories", default="")
    parser.add_argument(
        "--failure-categories",
        default="retrieval_miss,candidate_ambiguity",
        help="Comma-separated failure categories. Empty means all non-pass failures.",
    )
    parser.add_argument("--tool-sources", default="")
    parser.add_argument("--top-ks", default="")
    parser.add_argument("--case-ids-file", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--inspect-depth", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-distractors", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    bundle = build_hard_case_bundle(
        report=report,
        categories=_parse_categories(args.categories),
        data_root=args.data_root,
        ref=args.ref,
        top_k=args.top_k,
        inspect_depth=args.inspect_depth,
        failure_categories=_parse_strings(args.failure_categories),
        tool_sources=_parse_strings(args.tool_sources),
        top_ks=_parse_ints(args.top_ks),
        case_ids=load_case_ids(args.case_ids_file),
        limit=args.limit,
        max_distractors=args.max_distractors,
    )
    paths = write_hard_case_bundle(bundle, args.out_dir)
    if args.json:
        output = dict(bundle)
        output["paths"] = paths
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(bundle, paths=paths)
    return 0 if bundle["summary"]["cases"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
