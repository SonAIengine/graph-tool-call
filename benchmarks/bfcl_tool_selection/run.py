"""BFCL function-calling dataset tool-selection benchmark.

This runner reuses the official BFCL v4 JSONL data, but evaluates the
graph-tool-call retrieval layer rather than a model's final function-call AST.
It is a local BFCL-derived sanity check, not a BFCL leaderboard submission.
For each BFCL category, it builds one category-wide tool corpus from the
published function definitions and measures whether a user question retrieves
the ground-truth function names.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmarks.metrics import mrr, ndcg_at_k, recall_at_k
from graph_tool_call import ToolGraph, __version__

BFCL_REF = "f7cf7359b7ac615a0b294831c5ba2bc95ee4a000"
BFCL_REPO_RAW = "https://raw.githubusercontent.com/ShishirPatil/gorilla/{ref}"
BFCL_DATA_PATH = "berkeley-function-call-leaderboard/bfcl_eval/data"
BFCL_ANSWER_PATH = f"{BFCL_DATA_PATH}/possible_answer"
DEFAULT_CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
)


@dataclass
class BFCLCaseEvaluation:
    case_id: str
    category: str
    query: str
    expected_tools: list[str]
    retrieved: list[str]
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_k: float
    ndcg_at_5: float
    mrr: float
    all_tools_found_at_5: float
    all_tools_found_at_k: float
    argument_schema_coverage: float
    argument_schema_coverage_at_k: float
    latency_ms: float


@dataclass
class BFCLCategoryEvaluation:
    category: str
    case_count: int
    corpus_tool_count: int
    summary: dict[str, float | int | str]
    cases: list[BFCLCaseEvaluation]


def run_benchmark(
    *,
    categories: list[str] | None = None,
    data_root: Path | None = None,
    ref: str = BFCL_REF,
    top_k: int = 5,
    limit: int | None = None,
    case_ids: set[str] | None = None,
    min_recall_at_5: float = 0.0,
) -> dict[str, Any]:
    """Run the BFCL-derived deterministic tool-selection benchmark."""
    selected = categories or list(DEFAULT_CATEGORIES)
    evaluated = [
        evaluate_category(
            category,
            data_root=data_root,
            ref=ref,
            top_k=top_k,
            limit=limit,
            case_ids=case_ids,
            min_recall_at_5=min_recall_at_5,
        )
        for category in selected
    ]
    overall_rows = [case for category in evaluated for case in category.cases]
    return {
        "benchmark": "BFCL v4 Tool Selection",
        "methodology": "bfcl_function_call_tool_selection",
        "source": "local" if data_root else "official_gorilla_repo",
        "bfcl_ref": ref,
        "model": "none",
        "graph_tool_call_version": __version__,
        "top_k": top_k,
        "limit": limit,
        "case_filter_count": len(case_ids) if case_ids is not None else 0,
        "categories": [asdict(category) for category in evaluated],
        "summary": _summarize(overall_rows, min_recall_at_5=min_recall_at_5),
    }


def evaluate_category(
    category: str,
    *,
    data_root: Path | None,
    ref: str,
    top_k: int,
    limit: int | None,
    case_ids: set[str] | None,
    min_recall_at_5: float,
) -> BFCLCategoryEvaluation:
    question_rows = _load_jsonl(category, kind="question", data_root=data_root, ref=ref)
    answer_rows = _load_jsonl(category, kind="answer", data_root=data_root, ref=ref)
    answers_by_id = {str(row.get("id")): row for row in answer_rows}
    case_rows = _filter_case_rows(question_rows, case_ids)
    if limit is not None:
        case_rows = case_rows[: max(0, limit)]

    tg = _build_category_graph(category, question_rows)
    rows = [
        evaluate_case(
            question_row,
            answer_row=answers_by_id.get(str(question_row.get("id"))) or {},
            category=category,
            tg=tg,
            top_k=top_k,
        )
        for question_row in case_rows
    ]
    rows = [row for row in rows if row.expected_tools]
    return BFCLCategoryEvaluation(
        category=category,
        case_count=len(rows),
        corpus_tool_count=len(tg.tools),
        summary=_summarize(rows, min_recall_at_5=min_recall_at_5),
        cases=rows,
    )


def evaluate_case(
    question_row: dict[str, Any],
    *,
    answer_row: dict[str, Any],
    category: str,
    tg: ToolGraph,
    top_k: int,
) -> BFCLCaseEvaluation:
    query = _question_text(question_row)
    expected_tools = sorted(_expected_tool_names(answer_row))
    expected_arg_names = _expected_argument_names(answer_row)
    started = time.perf_counter()
    retrieved_tools = tg.retrieve(query, top_k=top_k)
    latency_ms = (time.perf_counter() - started) * 1000
    retrieved = [tool.name for tool in retrieved_tools]
    expected = set(expected_tools)
    return BFCLCaseEvaluation(
        case_id=str(question_row.get("id")),
        category=category,
        query=query,
        expected_tools=expected_tools,
        retrieved=retrieved,
        recall_at_1=recall_at_k(retrieved, expected, 1),
        recall_at_3=recall_at_k(retrieved, expected, min(3, top_k)),
        recall_at_5=recall_at_k(retrieved, expected, min(5, top_k)),
        recall_at_k=recall_at_k(retrieved, expected, top_k),
        ndcg_at_5=ndcg_at_k(retrieved, expected, min(5, top_k)),
        mrr=mrr(retrieved, expected),
        all_tools_found_at_5=1.0 if expected.issubset(set(retrieved[: min(5, top_k)])) else 0.0,
        all_tools_found_at_k=1.0 if expected.issubset(set(retrieved[:top_k])) else 0.0,
        argument_schema_coverage=_argument_schema_coverage(
            tg,
            expected_arg_names,
            retrieved=set(retrieved[: min(5, top_k)]),
        ),
        argument_schema_coverage_at_k=_argument_schema_coverage(
            tg,
            expected_arg_names,
            retrieved=set(retrieved[:top_k]),
        ),
        latency_ms=round(latency_ms, 3),
    )


def _build_category_graph(category: str, rows: list[dict[str, Any]]) -> ToolGraph:
    tools_by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        for raw_tool in row.get("function") or []:
            if not isinstance(raw_tool, dict) or not raw_tool.get("name"):
                continue
            name = str(raw_tool["name"])
            if name not in tools_by_name:
                tool = dict(raw_tool)
                metadata = dict(tool.get("metadata") or {})
                metadata.update({"bfcl_category": category, "source_label": "bfcl-v4"})
                tool["metadata"] = metadata
                tools_by_name[name] = tool

    tg = ToolGraph()
    tg.add_tools(list(tools_by_name.values()), detect_dependencies=False)
    return tg


def _load_jsonl(
    category: str,
    *,
    kind: str,
    data_root: Path | None,
    ref: str,
) -> list[dict[str, Any]]:
    filename = f"BFCL_v4_{category}.json"
    if data_root:
        root = data_root / ("possible_answer" if kind == "answer" else "")
        text = (root / filename).read_text(encoding="utf-8")
    else:
        base_path = BFCL_ANSWER_PATH if kind == "answer" else BFCL_DATA_PATH
        url = f"{BFCL_REPO_RAW.format(ref=ref)}/{base_path}/{filename}"
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            text = response.read().decode()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_case_ids(path: Path | None) -> set[str] | None:
    """Load a reusable BFCL case-id filter from JSON, JSONL, or plain text."""
    if path is None:
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return set()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        ids: set[str] = set()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("{"):
                try:
                    ids.update(_case_ids_from_items([json.loads(stripped)]))
                    continue
                except json.JSONDecodeError:
                    pass
            ids.add(stripped)
        return ids

    ids: set[str] = set()
    if isinstance(payload, list):
        ids.update(_case_ids_from_items(payload))
    elif isinstance(payload, dict):
        if "case_ids" in payload:
            ids.update(_case_ids_from_items(payload.get("case_ids") or []))
        elif "cases" in payload:
            ids.update(_case_ids_from_items(payload.get("cases") or []))
        else:
            ids.update(_case_ids_from_items([payload]))
    return ids


def _case_ids_from_items(items: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(items, list):
        items = [items]
    for item in items:
        if isinstance(item, str) and item.strip():
            ids.add(item.strip())
        elif isinstance(item, dict):
            case_id = item.get("case_id") or item.get("id")
            if case_id:
                ids.add(str(case_id))
    return ids


def _filter_case_rows(
    question_rows: list[dict[str, Any]],
    case_ids: set[str] | None,
) -> list[dict[str, Any]]:
    if case_ids is None:
        return question_rows
    return [row for row in question_rows if str(row.get("id")) in case_ids]


def _question_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    turns = row.get("question") or []
    for turn in turns:
        messages = turn if isinstance(turn, list) else [turn]
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                content = str(message.get("content") or "").strip()
                if content:
                    parts.append(content)
    return " ".join(parts)


def _expected_tool_names(answer_row: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for call in answer_row.get("ground_truth") or []:
        if isinstance(call, dict):
            names.update(str(name) for name in call)
    return names


def _expected_argument_names(answer_row: dict[str, Any]) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for call in answer_row.get("ground_truth") or []:
        if not isinstance(call, dict):
            continue
        for tool_name, args in call.items():
            if isinstance(args, dict):
                expected.setdefault(str(tool_name), set()).update(str(name) for name in args)
    return expected


def _argument_schema_coverage(
    tg: ToolGraph,
    expected_arg_names: dict[str, set[str]],
    *,
    retrieved: set[str],
) -> float:
    if not expected_arg_names:
        return 1.0
    coverages: list[float] = []
    tools = tg.tools
    for tool_name, expected_args in expected_arg_names.items():
        if not expected_args:
            coverages.append(1.0)
            continue
        if tool_name not in retrieved:
            coverages.append(0.0)
            continue
        schema = tools.get(tool_name)
        actual_args = {param.name for param in schema.parameters} if schema else set()
        coverages.append(len(expected_args & actual_args) / len(expected_args))
    return round(sum(coverages) / len(coverages), 6)


def _summarize(
    rows: list[BFCLCaseEvaluation],
    *,
    min_recall_at_5: float,
) -> dict[str, float | int | str]:
    summary: dict[str, float | int | str] = {
        "cases": len(rows),
        "recall_at_1": _mean(row.recall_at_1 for row in rows),
        "recall_at_3": _mean(row.recall_at_3 for row in rows),
        "recall_at_5": _mean(row.recall_at_5 for row in rows),
        "recall_at_k": _mean(row.recall_at_k for row in rows),
        "ndcg_at_5": _mean(row.ndcg_at_5 for row in rows),
        "mrr": _mean(row.mrr for row in rows),
        "all_tools_found_at_5": _mean(row.all_tools_found_at_5 for row in rows),
        "all_tools_found_at_k": _mean(row.all_tools_found_at_k for row in rows),
        "argument_schema_coverage": _mean(row.argument_schema_coverage for row in rows),
        "argument_schema_coverage_at_k": _mean(row.argument_schema_coverage_at_k for row in rows),
        "avg_latency_ms": _mean(row.latency_ms for row in rows),
    }
    summary["status"] = "pass" if summary["recall_at_5"] >= min_recall_at_5 else "fail"
    return summary


def _mean(values: Any) -> float:
    vals = [float(value) for value in values]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 6)


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    top_k = int(report["top_k"])
    print(f"{report['benchmark']}")
    print(
        f"model={report['model']} methodology={report['methodology']} "
        f"source={report['source']} ref={report['bfcl_ref']} status={summary['status']}"
    )
    print(
        "overall recall@1={r1:.2f} recall@3={r3:.2f} recall@5={r5:.2f} "
        "recall@{k}={rk:.2f} all_tools@{k}={allk:.2f} "
        "mrr={mrr_:.2f} ndcg@5={ndcg:.2f} schema@5={schema:.2f} "
        "schema@{k}={schemak:.2f} latency={latency:.2f}ms".format(
            k=top_k,
            r1=summary["recall_at_1"],
            r3=summary["recall_at_3"],
            r5=summary["recall_at_5"],
            rk=summary["recall_at_k"],
            allk=summary["all_tools_found_at_k"],
            mrr_=summary["mrr"],
            ndcg=summary["ndcg_at_5"],
            schema=summary["argument_schema_coverage"],
            schemak=summary["argument_schema_coverage_at_k"],
            latency=summary["avg_latency_ms"],
        )
    )
    for category in report["categories"]:
        cat_summary = category["summary"]
        print(
            "  {name}: cases={cases} tools={tools} recall@5={r5:.2f} "
            "recall@{k}={rk:.2f} all_tools@5={all_tools:.2f} "
            "all_tools@{k}={all_tools_k:.2f} mrr={mrr_:.2f}".format(
                k=top_k,
                name=category["category"],
                cases=category["case_count"],
                tools=category["corpus_tool_count"],
                r5=cat_summary["recall_at_5"],
                rk=cat_summary["recall_at_k"],
                all_tools=cat_summary["all_tools_found_at_5"],
                all_tools_k=cat_summary["all_tools_found_at_k"],
                mrr_=cat_summary["mrr"],
            )
        )


def _parse_categories(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated BFCL categories, e.g. simple_python,multiple.",
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--ref", default=BFCL_REF)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--case-ids-file",
        type=Path,
        default=None,
        help="Optional JSON/JSONL/text file containing BFCL case IDs to evaluate.",
    )
    parser.add_argument("--min-recall-at-5", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_benchmark(
        categories=_parse_categories(args.categories),
        data_root=args.data_root,
        ref=args.ref,
        top_k=args.top_k,
        limit=args.limit,
        case_ids=load_case_ids(args.case_ids_file),
        min_recall_at_5=args.min_recall_at_5,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
