"""Inspect BFCL tool-selection failures without calling an LLM.

The full BFCL-compatible model loop is intentionally expensive. This module
turns an existing failure report into a compact diagnostic artifact that
answers the next engineering questions:

* was the expected tool present in the current top-K?
* if not, did it appear by a deeper retrieval depth?
* which distractors displaced it?
* did the expected tool have any keyword/schema signal at all?

It is a deterministic research aid, not a leaderboard evaluator.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.bfcl_tool_selection.failures import extract_failure_cases
from benchmarks.bfcl_tool_selection.run import (
    BFCL_REF,
    DEFAULT_CATEGORIES,
    _build_category_graph,
    _expected_tool_names,
    _load_jsonl,
    _parse_categories,
    _question_text,
    load_case_ids,
)
from graph_tool_call import __version__
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.keyword import BM25Scorer

_EVIDENCE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "by",
        "is",
        "and",
        "or",
        "from",
        "was",
        "were",
        "be",
        "been",
        "with",
        "that",
        "this",
    }
)


def inspect_failures(
    *,
    report: dict[str, Any] | None = None,
    categories: list[str] | None = None,
    data_root: Path | None = None,
    ref: str = BFCL_REF,
    top_k: int = 5,
    inspect_depth: int = 20,
    case_ids: set[str] | None = None,
    failure_categories: set[str] | None = None,
    tool_sources: set[str] | None = None,
    top_ks: set[int] | None = None,
    limit: int | None = None,
    max_distractors: int = 5,
) -> dict[str, Any]:
    """Build a deterministic inspection report for BFCL failure cases."""
    top_k = max(1, top_k)
    selected_cases = _selected_failure_cases(
        report,
        failure_categories=failure_categories,
        categories=set(categories) if categories else None,
        tool_sources=tool_sources,
        top_ks=top_ks,
        limit=limit,
    )
    report_case_index = _index_report_cases(report)
    selected_case_ids = _merge_case_filters(case_ids, selected_cases)
    selected_categories = (
        categories or _categories_from_cases(selected_cases) or list(DEFAULT_CATEGORIES)
    )
    depth = max(top_k, inspect_depth)

    inspections: list[dict[str, Any]] = []
    for category in selected_categories:
        question_rows = _load_jsonl(category, kind="question", data_root=data_root, ref=ref)
        answer_rows = _load_jsonl(category, kind="answer", data_root=data_root, ref=ref)
        answers_by_id = {str(row.get("id")): row for row in answer_rows}
        rows = _filter_questions_for_inspection(question_rows, selected_case_ids)
        if limit is not None and selected_case_ids is None:
            rows = rows[: max(0, limit)]
        if not rows:
            continue

        tg = _build_category_graph(category, question_rows)
        for question_row in rows:
            case_id = str(question_row.get("id"))
            inspections.append(
                inspect_case(
                    question_row,
                    answer_row=answers_by_id.get(case_id) or {},
                    category=category,
                    report_case=report_case_index.get(case_id, {}),
                    failure_case=selected_cases.get(case_id, {}),
                    tg=tg,
                    top_k=top_k,
                    inspect_depth=depth,
                    max_distractors=max_distractors,
                )
            )

    return {
        "benchmark": "BFCL v4 Failure Inspector",
        "methodology": "bfcl_failure_inspection",
        "graph_tool_call_version": __version__,
        "model": "none",
        "bfcl_ref": ref,
        "source": "local" if data_root else "official_gorilla_repo",
        "top_k": top_k,
        "inspect_depth": depth,
        "case_filter_count": len(selected_case_ids) if selected_case_ids is not None else 0,
        "summary": _summarize(inspections, top_k=top_k, inspect_depth=depth),
        "cases": inspections,
    }


def inspect_case(
    question_row: dict[str, Any],
    *,
    answer_row: dict[str, Any],
    category: str,
    report_case: dict[str, Any],
    failure_case: dict[str, Any],
    tg: Any,
    top_k: int,
    inspect_depth: int,
    max_distractors: int,
) -> dict[str, Any]:
    """Inspect one BFCL case against the current retrieval implementation."""
    case_id = str(question_row.get("id"))
    query = _question_text(question_row)
    expected_tools = sorted(_expected_tool_names(answer_row))
    presented_results = tg.retrieve_with_scores(query, top_k=top_k)
    depth_results = (
        presented_results
        if inspect_depth <= top_k
        else tg.retrieve_with_scores(query, top_k=inspect_depth)
    )

    presented_names = [result.tool.name for result in presented_results]
    depth_names = [result.tool.name for result in depth_results]
    depth_by_name = {result.tool.name: result for result in depth_results}
    rank_by_name = {name: rank for rank, name in enumerate(depth_names, start=1)}
    top_k_boundary = depth_results[top_k - 1].score if len(depth_results) >= top_k else 0.0
    keyword_scores = _keyword_scores(tg, query)
    keyword_rank_by_name = _rank_scores(keyword_scores)
    query_tokens = _evidence_tokens(query)

    expected = [
        _expected_tool_entry(
            name,
            tool=tg.tools.get(name),
            result=depth_by_name.get(name),
            rank=rank_by_name.get(name),
            keyword_rank=keyword_rank_by_name.get(name),
            keyword_score=keyword_scores.get(name, 0.0),
            top_k=top_k,
            top_k_boundary=top_k_boundary,
            query_tokens=query_tokens,
        )
        for name in expected_tools
    ]
    expected_names = set(expected_tools)
    distractors = [
        _result_entry(result, rank=rank, query_tokens=query_tokens)
        for rank, result in enumerate(depth_results[:top_k], start=1)
        if result.tool.name not in expected_names
    ][:max_distractors]
    issues = _case_issues(expected, failure_case or report_case)

    return {
        "case_id": case_id,
        "category": category,
        "failure_category": str(
            failure_case.get("failure_category") or report_case.get("failure_category") or ""
        ),
        "query": query,
        "expected_tools": expected_tools,
        "expected": expected,
        "current_top_k": presented_names,
        "current_depth": depth_names,
        "observed_report_top_k": report_case.get("retrieved") or [],
        "predicted_tools": _predicted_tool_names(report_case),
        "missing_at_k": [entry["name"] for entry in expected if not entry["in_top_k"]],
        "missing_at_depth": [entry["name"] for entry in expected if not entry["in_inspect_depth"]],
        "distractors": distractors,
        "issues": issues,
    }


def _selected_failure_cases(
    report: dict[str, Any] | None,
    *,
    failure_categories: set[str] | None,
    categories: set[str] | None,
    tool_sources: set[str] | None,
    top_ks: set[int] | None,
    limit: int | None,
) -> dict[str, dict[str, Any]]:
    if report is None:
        return {}
    rows = extract_failure_cases(
        report,
        failure_categories=failure_categories,
        categories=categories,
        tool_sources=tool_sources,
        top_ks=top_ks,
        limit=limit,
    )
    return {str(row["case_id"]): row for row in rows}


def _merge_case_filters(
    case_ids: set[str] | None,
    selected_cases: dict[str, dict[str, Any]],
) -> set[str] | None:
    selected_ids = set(selected_cases)
    if case_ids is None:
        return selected_ids or None
    if not selected_ids:
        return set(case_ids)
    return selected_ids & set(case_ids)


def _categories_from_cases(cases: dict[str, dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    categories: list[str] = []
    for row in cases.values():
        category = str(row.get("category") or "")
        if category and category not in seen:
            seen.add(category)
            categories.append(category)
    return categories


def _filter_questions_for_inspection(
    question_rows: list[dict[str, Any]],
    case_ids: set[str] | None,
) -> list[dict[str, Any]]:
    if case_ids is None:
        return question_rows
    return [row for row in question_rows if str(row.get("id")) in case_ids]


def _keyword_scores(tg: Any, query: str) -> dict[str, float]:
    engine = tg._get_retrieval_engine()  # noqa: SLF001
    try:
        return engine._get_bm25().score(query)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return {}


def _rank_scores(scores: dict[str, float]) -> dict[str, int]:
    return {
        name: rank
        for rank, (name, _) in enumerate(
            sorted(scores.items(), key=lambda item: item[1], reverse=True), start=1
        )
    }


def _expected_tool_entry(
    name: str,
    *,
    tool: ToolSchema | None,
    result: Any,
    rank: int | None,
    keyword_rank: int | None,
    keyword_score: float,
    top_k: int,
    top_k_boundary: float,
    query_tokens: set[str],
) -> dict[str, Any]:
    score = float(result.score) if result is not None else 0.0
    score_gap = round(max(top_k_boundary - score, 0.0), 6) if result is not None else None
    return {
        "name": name,
        "rank": rank,
        "in_top_k": rank is not None and rank <= top_k,
        "in_inspect_depth": rank is not None,
        "score": round(score, 6),
        "score_gap_to_top_k_boundary": score_gap,
        "keyword_rank": keyword_rank,
        "keyword_score": round(float(keyword_score), 6),
        "score_breakdown": _score_breakdown(result),
        "matches": _match_evidence(tool, query_tokens),
    }


def _result_entry(result: Any, *, rank: int, query_tokens: set[str]) -> dict[str, Any]:
    return {
        "name": result.tool.name,
        "rank": rank,
        "description": result.tool.description,
        "score": round(float(result.score), 6),
        "score_breakdown": _score_breakdown(result),
        "matches": _match_evidence(result.tool, query_tokens),
    }


def _score_breakdown(result: Any) -> dict[str, float]:
    if result is None:
        return {
            "keyword": 0.0,
            "graph": 0.0,
            "embedding": 0.0,
            "annotation": 0.0,
        }
    return {
        "keyword": round(float(getattr(result, "keyword_score", 0.0)), 6),
        "graph": round(float(getattr(result, "graph_score", 0.0)), 6),
        "embedding": round(float(getattr(result, "embedding_score", 0.0)), 6),
        "annotation": round(float(getattr(result, "annotation_score", 0.0)), 6),
    }


def _match_evidence(tool: ToolSchema | None, query_tokens: set[str]) -> dict[str, list[str]]:
    if tool is None:
        return {"name": [], "description": [], "parameters": []}

    name_tokens = _evidence_tokens(tool.name)
    description_tokens = _evidence_tokens(tool.description)
    parameter_tokens: set[str] = set()
    for parameter in tool.parameters:
        parameter_tokens.update(_evidence_tokens(parameter.name))
        parameter_tokens.update(_evidence_tokens(parameter.description))

    return {
        "name": sorted(query_tokens & name_tokens),
        "description": sorted(query_tokens & description_tokens),
        "parameters": sorted(query_tokens & parameter_tokens),
    }


def _evidence_tokens(text: str) -> set[str]:
    return {
        token
        for token in BM25Scorer._tokenize(text)  # noqa: SLF001
        if token and token not in _EVIDENCE_STOPWORDS
    }


def _case_issues(
    expected: list[dict[str, Any]],
    report_case: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if not expected:
        return ["no_expected_tools"]
    missing_at_k = [entry for entry in expected if not entry["in_top_k"]]
    missing_at_depth = [entry for entry in expected if not entry["in_inspect_depth"]]
    near_misses = [
        entry for entry in missing_at_k if entry["in_inspect_depth"] and entry["rank"] is not None
    ]
    no_keyword = [entry for entry in missing_at_k if entry["keyword_score"] <= 0]

    if len(missing_at_depth) == len(expected):
        issues.append("all_expected_outside_inspect_depth")
    elif missing_at_depth:
        issues.append("some_expected_outside_inspect_depth")
    if near_misses:
        issues.append("expected_present_below_top_k")
    if missing_at_k and len(missing_at_k) < len(expected):
        issues.append("partial_multi_tool_at_k")
    if no_keyword:
        issues.append("weak_or_missing_keyword_signal")

    failure_category = str(report_case.get("failure_category") or "")
    if failure_category and failure_category != "pass":
        issues.append(f"reported_{failure_category}")
    return issues or ["needs_model_or_argument_analysis"]


def _index_report_cases(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if report is None:
        return indexed
    for run in _iter_report_runs(report):
        nested = run.get("report") if isinstance(run.get("report"), dict) else run
        for category in nested.get("categories") or []:
            for case in category.get("cases") or []:
                if not isinstance(case, dict):
                    continue
                case_id = str(case.get("case_id") or case.get("id") or "")
                if case_id and case_id not in indexed:
                    indexed[case_id] = case
    return indexed


def _iter_report_runs(report: dict[str, Any]) -> list[dict[str, Any]]:
    runs = report.get("runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, dict)]
    return [report]


def _predicted_tool_names(report_case: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for call in report_case.get("predicted_calls") or []:
        if isinstance(call, dict) and call.get("name"):
            names.append(str(call["name"]))
    return names


def _summarize(
    cases: list[dict[str, Any]],
    *,
    top_k: int,
    inspect_depth: int,
) -> dict[str, Any]:
    categories = Counter(str(case["category"]) for case in cases)
    failure_categories = Counter(str(case["failure_category"] or "unknown") for case in cases)
    issue_counts = Counter(issue for case in cases for issue in case["issues"])
    missing_tools = Counter(tool for case in cases for tool in case["missing_at_k"])
    distractors = Counter(
        distractor["name"] for case in cases for distractor in case["distractors"]
    )
    expected_entries = [entry for case in cases for entry in case["expected"]]
    rank_buckets = _rank_buckets(expected_entries, top_k=top_k, inspect_depth=inspect_depth)

    all_found_at_k = sum(1 for case in cases if not case["missing_at_k"])
    all_found_at_depth = sum(1 for case in cases if not case["missing_at_depth"])
    return {
        "cases": len(cases),
        "expected_tool_mentions": len(expected_entries),
        "all_expected_found_at_k": _ratio(all_found_at_k, len(cases)),
        "all_expected_found_at_depth": _ratio(all_found_at_depth, len(cases)),
        "missing_tool_mentions_at_k": sum(len(case["missing_at_k"]) for case in cases),
        "missing_tool_mentions_at_depth": sum(len(case["missing_at_depth"]) for case in cases),
        "rank_buckets": rank_buckets,
        "categories": dict(sorted(categories.items())),
        "failure_categories": dict(sorted(failure_categories.items())),
        "issues": dict(issue_counts.most_common()),
        "top_missing_tools": _counter_rows(missing_tools),
        "top_distractors": _counter_rows(distractors),
    }


def _rank_buckets(
    expected_entries: list[dict[str, Any]],
    *,
    top_k: int,
    inspect_depth: int,
) -> dict[str, int]:
    buckets = {
        f"top_{top_k}": 0,
        f"top_{inspect_depth}": 0,
        "outside_inspect_depth": 0,
    }
    for entry in expected_entries:
        rank = entry.get("rank")
        if rank is None:
            buckets["outside_inspect_depth"] += 1
        elif rank <= top_k:
            buckets[f"top_{top_k}"] += 1
        else:
            buckets[f"top_{inspect_depth}"] += 1
    return buckets


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _counter_rows(counter: Counter[str], *, limit: int = 20) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit) if name]


def print_report(report: dict[str, Any]) -> None:
    """Print a compact terminal summary."""
    summary = report["summary"]
    print(report["benchmark"])
    print(
        "cases={cases} expected_tools={expected} top_k={top_k} depth={depth} "
        "all_found@k={found_k:.2f} all_found@depth={found_depth:.2f}".format(
            cases=summary["cases"],
            expected=summary["expected_tool_mentions"],
            top_k=report["top_k"],
            depth=report["inspect_depth"],
            found_k=summary["all_expected_found_at_k"],
            found_depth=summary["all_expected_found_at_depth"],
        )
    )
    print(f"rank_buckets={summary['rank_buckets']}")
    if summary["issues"]:
        print("issues=" + ", ".join(f"{k}:{v}" for k, v in summary["issues"].items()))
    if summary["top_missing_tools"]:
        missing = ", ".join(
            f"{row['name']}:{row['count']}" for row in summary["top_missing_tools"][:10]
        )
        print(f"top_missing_tools={missing}")
    if summary["top_distractors"]:
        distractors = ", ".join(
            f"{row['name']}:{row['count']}" for row in summary["top_distractors"][:10]
        )
        print(f"top_distractors={distractors}")


def _parse_strings(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def _parse_ints(value: str | None) -> set[int] | None:
    if not value:
        return None
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--ref", default=BFCL_REF)
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated BFCL categories. Defaults to report categories or all four.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--inspect-depth", type=int, default=20)
    parser.add_argument("--case-ids-file", type=Path, default=None)
    parser.add_argument(
        "--failure-categories",
        default="retrieval_miss,candidate_ambiguity",
        help="Comma-separated failure categories to inspect. Empty means all non-pass failures.",
    )
    parser.add_argument("--tool-sources", default="", help="Comma-separated tool sources")
    parser.add_argument("--top-ks", default="", help="Comma-separated report top-K values")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-distractors", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8")) if args.report else None
    categories = _parse_categories(args.categories) if args.categories else None
    output = inspect_failures(
        report=report,
        categories=categories,
        data_root=args.data_root,
        ref=args.ref,
        top_k=args.top_k,
        inspect_depth=args.inspect_depth,
        case_ids=load_case_ids(args.case_ids_file),
        failure_categories=_parse_strings(args.failure_categories),
        tool_sources=_parse_strings(args.tool_sources),
        top_ks=_parse_ints(args.top_ks),
        limit=args.limit,
        max_distractors=args.max_distractors,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(output)
    return 0 if output["summary"]["cases"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
