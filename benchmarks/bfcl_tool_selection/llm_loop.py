"""BFCL-compatible model-in-the-loop tool-call benchmark.

This runner uses the public BFCL v4 function-calling JSONL files and asks a
native tool-calling model to emit function calls. It can either pass the
official per-case BFCL tool list to the model (``--tool-source row``) or place
graph-tool-call in front of the model by retrieving top-K tools from a
category-wide corpus (``--tool-source retrieved``).

The matcher intentionally follows the main BFCL AST-checker rules that matter
for Python single-turn categories:

* function-call count must match;
* parallel categories are matched without order;
* unexpected parameters fail;
* missing parameters fail unless the BFCL possible-answer list contains "";
* strings are normalized by removing spaces and common punctuation.

It is still a local BFCL-compatible check, not an official leaderboard run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.bfcl_tool_selection.run import (
    BFCL_REF,
    DEFAULT_CATEGORIES,
    _build_category_graph,
    _filter_case_rows,
    _load_jsonl,
    _parse_categories,
    _question_text,
    load_case_ids,
)
from benchmarks.metrics import recall_at_k
from benchmarks.xgen_tool_graph.llm_loop import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    ChatResponse,
    _post_json,
    _redacted_url,
)
from graph_tool_call import ToolGraph, __version__
from graph_tool_call.graphify import build_tool_equivalence_groups

DEFAULT_OFFICIAL_MODEL_NAME = "qwen3-32b-FC"
BFCL_RESULT_ARGUMENT_FORMATS = ("json-string", "decoded")
MODEL_CASE_CACHE_VERSION = 9


@dataclass(frozen=True)
class ExpectedToolCall:
    name: str
    arguments: dict[str, list[Any]]


@dataclass(frozen=True)
class PredictedToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class BFCLModelCaseEvaluation:
    case_id: str
    category: str
    query: str
    tool_source: str
    expected_calls: list[ExpectedToolCall]
    predicted_calls: list[PredictedToolCall]
    retrieved: list[str]
    tools_presented: list[str]
    retrieval_recall_at_k: float
    all_expected_tools_retrieved: float
    model_tool_call_rate: float
    function_name_exact_match: float
    argument_name_coverage: float
    argument_value_exact_match: float
    strict_exact_match: float
    official_ast_exact_match: float
    evaluator_exact_match: float
    equivalence_adjusted_exact_match: float
    input_tokens: int
    output_tokens: int
    latency_ms: float
    failure_category: str = "pass"
    error: str = ""
    official_error_type: str = ""
    official_error: str = ""
    raw_content: str = ""
    failure_tags: list[str] = field(default_factory=list)


@dataclass
class BFCLModelCategoryEvaluation:
    category: str
    case_count: int
    corpus_tool_count: int
    summary: dict[str, Any]
    cases: list[BFCLModelCaseEvaluation]


def run_model_benchmark(
    *,
    model: str = DEFAULT_MODEL,
    llm_url: str = DEFAULT_OLLAMA_URL,
    categories: list[str] | None = None,
    data_root: Path | None = None,
    ref: str = BFCL_REF,
    top_k: int = 5,
    limit: int | None = None,
    case_ids: set[str] | None = None,
    tool_source: str = "retrieved",
    tool_choice: str = "required",
    evaluator: str = "local",
    official_model_name: str = DEFAULT_OFFICIAL_MODEL_NAME,
    cache_dir: Path | None = None,
    cache_namespace: str = "",
    refresh_cache: bool = False,
    timeout: int = 180,
    disable_thinking: bool = False,
    min_exact_match: float = 0.0,
    concurrency: int = 1,
    progress: bool = False,
    progress_every: int = 25,
    retrieval_rank_hints: bool = False,
    candidate_selection_guidance: bool = False,
    cohesive_namespace_candidates: bool = False,
) -> dict[str, Any]:
    """Run BFCL-compatible native tool-call evaluation with a real model."""
    if evaluator == "official":
        _ensure_official_checker_available()

    selected = categories or list(DEFAULT_CATEGORIES)
    evaluated = [
        evaluate_category_model(
            category,
            model=model,
            llm_url=llm_url,
            data_root=data_root,
            ref=ref,
            top_k=top_k,
            limit=limit,
            case_ids=case_ids,
            tool_source=tool_source,
            tool_choice=tool_choice,
            evaluator=evaluator,
            official_model_name=official_model_name,
            cache_dir=cache_dir,
            cache_namespace=cache_namespace,
            refresh_cache=refresh_cache,
            timeout=timeout,
            disable_thinking=disable_thinking,
            min_exact_match=min_exact_match,
            concurrency=concurrency,
            progress=progress,
            progress_every=progress_every,
            retrieval_rank_hints=retrieval_rank_hints,
            candidate_selection_guidance=candidate_selection_guidance,
            cohesive_namespace_candidates=cohesive_namespace_candidates,
        )
        for category in selected
    ]
    overall_rows = [case for category in evaluated for case in category.cases]
    return {
        "benchmark": "BFCL v4 Model Tool Calls",
        "methodology": "bfcl_compatible_model_tool_calls",
        "source": "local" if data_root else "official_gorilla_repo",
        "bfcl_ref": ref,
        "model": model,
        "llm_url": _redacted_url(llm_url),
        "tool_source": tool_source,
        "tool_choice": tool_choice,
        "evaluator": evaluator,
        "official_model_name": official_model_name if evaluator == "official" else "",
        "disable_thinking": disable_thinking,
        "graph_tool_call_version": __version__,
        "top_k": top_k,
        "limit": limit,
        "case_filter_count": len(case_ids) if case_ids is not None else 0,
        "cache_dir": str(cache_dir) if cache_dir else "",
        "cache_namespace": cache_namespace,
        "concurrency": max(1, concurrency),
        "progress": progress,
        "retrieval_rank_hints": retrieval_rank_hints,
        "candidate_selection_guidance": candidate_selection_guidance,
        "cohesive_namespace_candidates": cohesive_namespace_candidates,
        "categories": [asdict(category) for category in evaluated],
        "summary": _summarize(overall_rows, min_exact_match=min_exact_match),
    }


def evaluate_category_model(
    category: str,
    *,
    model: str,
    llm_url: str,
    data_root: Path | None,
    ref: str,
    top_k: int,
    limit: int | None,
    case_ids: set[str] | None,
    tool_source: str,
    tool_choice: str,
    evaluator: str,
    official_model_name: str,
    cache_dir: Path | None,
    cache_namespace: str,
    refresh_cache: bool,
    timeout: int,
    disable_thinking: bool,
    min_exact_match: float,
    concurrency: int = 1,
    progress: bool = False,
    progress_every: int = 25,
    retrieval_rank_hints: bool = False,
    candidate_selection_guidance: bool = False,
    cohesive_namespace_candidates: bool = False,
) -> BFCLModelCategoryEvaluation:
    question_rows = _load_jsonl(category, kind="question", data_root=data_root, ref=ref)
    answer_rows = _load_jsonl(category, kind="answer", data_root=data_root, ref=ref)
    answers_by_id = {str(row.get("id")): row for row in answer_rows}
    case_rows = _filter_case_rows(question_rows, case_ids)
    if limit is not None:
        case_rows = case_rows[: max(0, limit)]

    tg = _build_category_graph(category, question_rows)
    tools_by_name = _tools_by_name(question_rows)
    rows = _evaluate_category_cases(
        case_rows,
        answers_by_id=answers_by_id,
        category=category,
        model=model,
        llm_url=llm_url,
        tg=tg,
        tools_by_name=tools_by_name,
        ref=ref,
        top_k=top_k,
        tool_source=tool_source,
        tool_choice=tool_choice,
        evaluator=evaluator,
        official_model_name=official_model_name,
        cache_dir=cache_dir,
        cache_namespace=cache_namespace,
        refresh_cache=refresh_cache,
        timeout=timeout,
        disable_thinking=disable_thinking,
        concurrency=concurrency,
        progress=progress,
        progress_every=progress_every,
        retrieval_rank_hints=retrieval_rank_hints,
        candidate_selection_guidance=candidate_selection_guidance,
        cohesive_namespace_candidates=cohesive_namespace_candidates,
    )
    rows = [row for row in rows if row.expected_calls]
    return BFCLModelCategoryEvaluation(
        category=category,
        case_count=len(rows),
        corpus_tool_count=len(tg.tools),
        summary=_summarize(rows, min_exact_match=min_exact_match),
        cases=rows,
    )


def _evaluate_category_cases(
    case_rows: list[dict[str, Any]],
    *,
    answers_by_id: dict[str, dict[str, Any]],
    category: str,
    model: str,
    llm_url: str,
    tg: ToolGraph,
    tools_by_name: dict[str, dict[str, Any]],
    ref: str,
    top_k: int,
    tool_source: str,
    tool_choice: str,
    evaluator: str,
    official_model_name: str,
    cache_dir: Path | None,
    cache_namespace: str,
    refresh_cache: bool,
    timeout: int,
    disable_thinking: bool,
    concurrency: int,
    progress: bool,
    progress_every: int,
    retrieval_rank_hints: bool,
    candidate_selection_guidance: bool,
    cohesive_namespace_candidates: bool,
) -> list[BFCLModelCaseEvaluation]:
    max_workers = max(1, concurrency)
    started = time.perf_counter()
    rows: list[BFCLModelCaseEvaluation | None] = [None] * len(case_rows)
    cache_hits = 0

    if max_workers == 1:
        for index, question_row in enumerate(case_rows):
            row, cache_hit = _evaluate_or_read_case(
                question_row,
                answers_by_id=answers_by_id,
                category=category,
                model=model,
                llm_url=llm_url,
                tg=tg,
                tools_by_name=tools_by_name,
                ref=ref,
                top_k=top_k,
                tool_source=tool_source,
                tool_choice=tool_choice,
                evaluator=evaluator,
                official_model_name=official_model_name,
                cache_dir=cache_dir,
                cache_namespace=cache_namespace,
                refresh_cache=refresh_cache,
                timeout=timeout,
                disable_thinking=disable_thinking,
                retrieval_rank_hints=retrieval_rank_hints,
                candidate_selection_guidance=candidate_selection_guidance,
                cohesive_namespace_candidates=cohesive_namespace_candidates,
            )
            rows[index] = row
            cache_hits += int(cache_hit)
            _print_progress(
                category=category,
                tool_source=tool_source,
                top_k=top_k,
                completed=index + 1,
                total=len(case_rows),
                cache_hits=cache_hits,
                started=started,
                progress=progress,
                progress_every=progress_every,
            )
        return [row for row in rows if row is not None]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _evaluate_or_read_case,
                question_row,
                answers_by_id=answers_by_id,
                category=category,
                model=model,
                llm_url=llm_url,
                tg=tg,
                tools_by_name=tools_by_name,
                ref=ref,
                top_k=top_k,
                tool_source=tool_source,
                tool_choice=tool_choice,
                evaluator=evaluator,
                official_model_name=official_model_name,
                cache_dir=cache_dir,
                cache_namespace=cache_namespace,
                refresh_cache=refresh_cache,
                timeout=timeout,
                disable_thinking=disable_thinking,
                retrieval_rank_hints=retrieval_rank_hints,
                candidate_selection_guidance=candidate_selection_guidance,
                cohesive_namespace_candidates=cohesive_namespace_candidates,
            ): index
            for index, question_row in enumerate(case_rows)
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            index = futures[future]
            row, cache_hit = future.result()
            rows[index] = row
            cache_hits += int(cache_hit)
            _print_progress(
                category=category,
                tool_source=tool_source,
                top_k=top_k,
                completed=completed,
                total=len(case_rows),
                cache_hits=cache_hits,
                started=started,
                progress=progress,
                progress_every=progress_every,
            )
    return [row for row in rows if row is not None]


def _evaluate_or_read_case(
    question_row: dict[str, Any],
    *,
    answers_by_id: dict[str, dict[str, Any]],
    category: str,
    model: str,
    llm_url: str,
    tg: ToolGraph,
    tools_by_name: dict[str, dict[str, Any]],
    ref: str,
    top_k: int,
    tool_source: str,
    tool_choice: str,
    evaluator: str,
    official_model_name: str,
    cache_dir: Path | None,
    cache_namespace: str,
    refresh_cache: bool,
    timeout: int,
    disable_thinking: bool,
    retrieval_rank_hints: bool,
    candidate_selection_guidance: bool,
    cohesive_namespace_candidates: bool,
) -> tuple[BFCLModelCaseEvaluation, bool]:
    answer_row = answers_by_id.get(str(question_row.get("id"))) or {}
    cache_path = _case_cache_path(
        cache_dir,
        question_row=question_row,
        category=category,
        model=model,
        llm_url=llm_url,
        ref=ref,
        top_k=top_k,
        tool_source=tool_source,
        tool_choice=tool_choice,
        evaluator=evaluator,
        official_model_name=official_model_name,
        timeout=timeout,
        disable_thinking=disable_thinking,
        cache_namespace=cache_namespace,
        retrieval_rank_hints=retrieval_rank_hints,
        candidate_selection_guidance=candidate_selection_guidance,
        cohesive_namespace_candidates=cohesive_namespace_candidates,
    )
    row = None if refresh_cache else _read_case_cache(cache_path)
    if row is not None:
        _ensure_failure_tags(row, tools_by_name=tools_by_name)
        return row, True

    row = evaluate_model_case(
        question_row,
        answer_row=answer_row,
        category=category,
        model=model,
        llm_url=llm_url,
        tg=tg,
        tools_by_name=tools_by_name,
        top_k=top_k,
        tool_source=tool_source,
        tool_choice=tool_choice,
        evaluator=evaluator,
        official_model_name=official_model_name,
        timeout=timeout,
        disable_thinking=disable_thinking,
        retrieval_rank_hints=retrieval_rank_hints,
        candidate_selection_guidance=candidate_selection_guidance,
        cohesive_namespace_candidates=cohesive_namespace_candidates,
    )
    _write_case_cache(cache_path, row)
    return row, False


def _print_progress(
    *,
    category: str,
    tool_source: str,
    top_k: int,
    completed: int,
    total: int,
    cache_hits: int,
    started: float,
    progress: bool,
    progress_every: int,
) -> None:
    if not progress or total <= 0:
        return
    interval = max(1, progress_every)
    if completed not in {1, total} and completed % interval:
        return
    elapsed = time.perf_counter() - started
    model_calls = completed - cache_hits
    print(
        f"[bfcl] {category} {tool_source} k={top_k} {completed}/{total} "
        f"cache_hit={cache_hits} model_calls={model_calls} elapsed={elapsed:.1f}s",
        file=sys.stderr,
        flush=True,
    )


def evaluate_model_case(
    question_row: dict[str, Any],
    *,
    answer_row: dict[str, Any],
    category: str,
    model: str,
    llm_url: str,
    tg: ToolGraph,
    tools_by_name: dict[str, dict[str, Any]],
    top_k: int,
    tool_source: str,
    tool_choice: str,
    evaluator: str,
    official_model_name: str,
    timeout: int,
    disable_thinking: bool,
    retrieval_rank_hints: bool,
    candidate_selection_guidance: bool,
    cohesive_namespace_candidates: bool,
) -> BFCLModelCaseEvaluation:
    query = _question_text(question_row)
    expected_calls = _expected_calls(answer_row)
    expected_names = {call.name for call in expected_calls}

    started = time.perf_counter()
    retrieved = [tool.name for tool in tg.retrieve(query, top_k=top_k)]
    if tool_source == "row":
        presented_tools = _case_tool_names(question_row)
    elif tool_source == "retrieved":
        presented_tools = _cohesive_namespace_candidates(
            retrieved,
            query=query,
            enabled=cohesive_namespace_candidates,
        )
    else:
        raise ValueError(f"Unknown tool_source: {tool_source}")

    raw_tools = [tools_by_name[name] for name in presented_tools if name in tools_by_name]
    model_tools, safe_name_map = _prepare_tools_for_model(
        raw_tools,
        rank_hints=retrieval_rank_hints and tool_source == "retrieved",
        rank_by_name={name: index + 1 for index, name in enumerate(retrieved)},
    )
    response = _chat(
        model=model,
        llm_url=llm_url,
        messages=_messages_for_case(
            query,
            candidate_selection_guidance=candidate_selection_guidance,
        ),
        tools=model_tools,
        tool_choice=tool_choice,
        timeout=timeout,
        disable_thinking=disable_thinking,
    )
    predicted_calls = _extract_predicted_calls(response, safe_name_map)
    match = _evaluate_predictions(expected_calls, predicted_calls, category=category)
    official = (
        _evaluate_official_predictions(
            function_descriptions=list(question_row.get("function") or []),
            answer_row=answer_row,
            predicted_calls=predicted_calls,
            category=category,
            official_model_name=official_model_name,
        )
        if evaluator == "official"
        else _empty_official_result()
    )
    evaluator_exact_match = (
        official["official_ast_exact_match"]
        if evaluator == "official"
        else match["strict_exact_match"]
    )
    equivalence_adjusted_exact_match = _equivalence_adjusted_exact_match(
        expected_calls,
        predicted_calls,
        tools_by_name=tools_by_name,
        category=category,
        strict_exact_match=match["strict_exact_match"],
    )
    error = response.error or official["official_error"] or match["error"]
    failure_category = _classify_failure(
        expected_calls=expected_calls,
        predicted_calls=predicted_calls,
        retrieved=retrieved,
        tools_presented=presented_tools,
        match=match,
        official=official,
        evaluator_exact_match=evaluator_exact_match,
        response_error=response.error,
    )
    failure_tags = _failure_tags(
        expected_calls=expected_calls,
        predicted_calls=predicted_calls,
        tools_by_name=tools_by_name,
        failure_category=failure_category,
    )
    latency_ms = (time.perf_counter() - started) * 1000

    return BFCLModelCaseEvaluation(
        case_id=str(question_row.get("id")),
        category=category,
        query=query,
        tool_source=tool_source,
        expected_calls=expected_calls,
        predicted_calls=predicted_calls,
        retrieved=retrieved,
        tools_presented=presented_tools,
        retrieval_recall_at_k=recall_at_k(retrieved, expected_names, top_k),
        all_expected_tools_retrieved=1.0 if expected_names.issubset(set(retrieved)) else 0.0,
        model_tool_call_rate=1.0 if predicted_calls else 0.0,
        function_name_exact_match=match["function_name_exact_match"],
        argument_name_coverage=match["argument_name_coverage"],
        argument_value_exact_match=match["argument_value_exact_match"],
        strict_exact_match=match["strict_exact_match"],
        official_ast_exact_match=official["official_ast_exact_match"],
        evaluator_exact_match=evaluator_exact_match,
        equivalence_adjusted_exact_match=equivalence_adjusted_exact_match,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_ms=round(latency_ms, 3),
        failure_category=failure_category,
        error=error,
        official_error_type=official["official_error_type"],
        official_error=official["official_error"],
        raw_content=response.content,
        failure_tags=failure_tags,
    )


def _messages_for_case(
    query: str,
    *,
    candidate_selection_guidance: bool = False,
) -> list[dict[str, str]]:
    system = (
        "You are evaluating function calling. Use only the provided tools. "
        "Emit native tool calls only, with no prose. If the request needs "
        "multiple independent actions, emit one tool call for each action. "
        "Use exact argument values from the user request. Omit optional "
        "arguments unless the request explicitly sets them."
    )
    if candidate_selection_guidance:
        system += (
            " Candidate selection guidance: if several tools look similar, prefer the most "
            "specific tool whose name and description match the exact requested action. "
            "For related multi-call requests, prefer tools from the same namespace or API "
            "family when their actions match. Avoid adding a generic all-in-one or lower-level "
            "helper tool when one provided tool already satisfies the requested operation. "
            "Do not decompose one requested operation into multiple tool calls unless the user "
            "asks for separate actions."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": query}]


def _cohesive_namespace_candidates(
    names: list[str],
    *,
    query: str,
    enabled: bool,
) -> list[str]:
    """Prefer a cohesive dotted namespace family for multi-action retrieved sets.

    This is an opt-in model-loop ablation. It does not change graph retrieval:
    the report still records the raw retrieved names, while ``tools_presented``
    shows the compressed LLM-facing set.
    """

    if not enabled or not _looks_multi_intent(query):
        return list(names)

    query_terms = _candidate_query_terms(query)
    groups: dict[str, list[str]] = {}
    for name in names:
        namespace = _dotted_namespace(name)
        if namespace:
            groups.setdefault(namespace, []).append(name)
    first_namespace = _dotted_namespace(names[0]) if names else ""
    cohesive_namespaces = {
        namespace
        for namespace, members in groups.items()
        if len(members) >= 2 and (namespace == first_namespace or namespace in query_terms)
    }
    if not cohesive_namespaces:
        return list(names)

    selected = [
        name
        for name in names
        if _dotted_namespace(name) in cohesive_namespaces or _dotted_namespace(name) in query_terms
    ]
    return selected or list(names)


def _looks_multi_intent(query: str) -> bool:
    text = f" {str(query or '').lower()} "
    if any(marker in text for marker in (" also ", " as well ", " then ", "그리고", "또")):
        return True
    return bool(
        re.search(
            r"\band\s+(also\s+)?(find|calculate|compute|get|retrieve|determine|check|show)\b",
            text,
        )
    )


def _dotted_namespace(name: str) -> str:
    text = str(name or "")
    if "." not in text:
        return ""
    namespace, _sep, _rest = text.partition(".")
    return namespace.strip().lower()


def _candidate_query_terms(query: str) -> set[str]:
    text = str(query or "").strip().lower()
    terms = {term for term in re.split(r"[^a-z0-9]+", text) if term}
    singular_terms = {
        term[:-1]
        for term in terms
        if len(term) > 3 and term.endswith("s") and not term.endswith("ss")
    }
    return terms | singular_terms


def _chat(
    *,
    model: str,
    llm_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str,
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    if "/v1" in llm_url.rstrip("/"):
        return _chat_openai_compatible(
            model=model,
            base_url=llm_url,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            timeout=timeout,
            disable_thinking=disable_thinking,
        )
    return _chat_ollama(
        model=model,
        url=llm_url,
        messages=messages,
        tools=tools,
        timeout=timeout,
        disable_thinking=disable_thinking,
    )


def _chat_openai_compatible(
    *,
    model: str,
    base_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str,
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": 768,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if disable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key and not base_url.startswith(("http://localhost", "http://127.0.0.1")):
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.perf_counter()
    try:
        body = _post_json(f"{base_url.rstrip('/')}/chat/completions", payload, headers, timeout)
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(error=str(exc), latency_ms=(time.perf_counter() - started) * 1000)

    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = body.get("usage") or {}
    return ChatResponse(
        content=str(message.get("content") or ""),
        tool_calls=list(message.get("tool_calls") or []),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def _chat_ollama(
    *,
    model: str,
    url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096, "num_predict": 768, "temperature": 0},
    }
    if tools:
        payload["tools"] = tools
    if disable_thinking:
        payload["think"] = False

    started = time.perf_counter()
    try:
        body = _post_json(url, payload, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(error=str(exc), latency_ms=(time.perf_counter() - started) * 1000)

    message = body.get("message") or {}
    return ChatResponse(
        content=str(message.get("content") or ""),
        tool_calls=list(message.get("tool_calls") or []),
        input_tokens=int(body.get("prompt_eval_count") or 0),
        output_tokens=int(body.get("eval_count") or 0),
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def _prepare_tools_for_model(
    raw_tools: list[dict[str, Any]],
    *,
    rank_hints: bool = False,
    rank_by_name: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    used_names: dict[str, str] = {}
    safe_to_original: dict[str, str] = {}
    model_tools: list[dict[str, Any]] = []
    for raw_tool in raw_tools:
        original_name = str(raw_tool.get("name") or "")
        if not original_name:
            continue
        safe_name = _safe_tool_name(original_name, used_names)
        safe_to_original[safe_name] = original_name
        model_tools.append(
            {
                "type": "function",
                "function": {
                    "name": safe_name,
                    "description": _model_tool_description(
                        raw_tool,
                        rank_hints=rank_hints,
                        rank=rank_by_name.get(original_name) if rank_by_name else None,
                    ),
                    "parameters": _normalize_parameters(raw_tool.get("parameters") or {}),
                },
            }
        )
    return model_tools, safe_to_original


def _model_tool_description(
    raw_tool: dict[str, Any],
    *,
    rank_hints: bool,
    rank: int | None,
) -> str:
    description = str(raw_tool.get("description") or "")
    if not rank_hints or rank is None:
        return description
    return (
        f"Graph retrieval rank #{rank} for the current user query. "
        f"Prefer lower rank numbers when multiple tools look similar. {description}"
    ).strip()


def _safe_tool_name(original_name: str, used_names: dict[str, str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]", "_", original_name).strip("_") or "tool"
    if len(base) > 64:
        base = f"{base[:55]}_{_hash(original_name)}"
    candidate = base[:64]
    if candidate not in used_names or used_names[candidate] == original_name:
        used_names[candidate] = original_name
        return candidate

    suffix = f"_{_hash(original_name)}"
    candidate = f"{base[: 64 - len(suffix)]}{suffix}"
    used_names[candidate] = original_name
    return candidate


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:8]  # noqa: S324


def _normalize_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_schema(schema)
    normalized["type"] = "object"
    normalized.setdefault("properties", {})
    normalized["required"] = [
        name for name in normalized.get("required", []) if name in normalized["properties"]
    ]
    normalized.setdefault("additionalProperties", False)
    return normalized


def _normalize_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type":
            normalized[key] = _json_schema_type(value)
        elif key == "properties" and isinstance(value, dict):
            normalized[key] = {str(name): _normalize_schema(child) for name, child in value.items()}
        elif key == "items":
            normalized[key] = _normalize_schema(value)
        elif key in {"anyOf", "oneOf", "allOf"} and isinstance(value, list):
            normalized[key] = [_normalize_schema(child) for child in value]
        elif key in {
            "description",
            "enum",
            "required",
            "default",
            "minimum",
            "maximum",
            "minItems",
            "maxItems",
        }:
            normalized[key] = value

    if normalized.get("type") == "array" and "items" not in normalized:
        normalized["items"] = {}
    return normalized


def _json_schema_type(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_schema_type(item) for item in value]
    mapping = {
        "dict": "object",
        "object": "object",
        "array": "array",
        "tuple": "array",
        "list": "array",
        "string": "string",
        "str": "string",
        "integer": "integer",
        "int": "integer",
        "float": "number",
        "double": "number",
        "number": "number",
        "boolean": "boolean",
        "bool": "boolean",
        "any": "string",
    }
    return mapping.get(str(value), "string")


def _extract_predicted_calls(
    response: ChatResponse,
    safe_name_map: dict[str, str],
) -> list[PredictedToolCall]:
    calls: list[PredictedToolCall] = []
    for raw_call in response.tool_calls:
        fn = raw_call.get("function") if isinstance(raw_call, dict) else None
        if not isinstance(fn, dict):
            fn = raw_call if isinstance(raw_call, dict) else {}
        fallback_name = raw_call.get("name") if isinstance(raw_call, dict) else ""
        raw_name = str(fn.get("name") or fallback_name or "")
        if not raw_name:
            continue
        args = fn.get("arguments")
        if args is None and isinstance(raw_call, dict):
            args = raw_call.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append(PredictedToolCall(name=safe_name_map.get(raw_name, raw_name), arguments=args))
    return calls


def _expected_calls(answer_row: dict[str, Any]) -> list[ExpectedToolCall]:
    calls: list[ExpectedToolCall] = []
    for raw_call in answer_row.get("ground_truth") or []:
        if not isinstance(raw_call, dict):
            continue
        for name, arguments in raw_call.items():
            calls.append(
                ExpectedToolCall(
                    name=str(name),
                    arguments={
                        str(arg_name): _possible_values(values)
                        for arg_name, values in (arguments or {}).items()
                    },
                )
            )
    return calls


def _possible_values(values: Any) -> list[Any]:
    if isinstance(values, list):
        return values
    return [values]


def _evaluate_predictions(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    *,
    category: str,
) -> dict[str, Any]:
    function_name_exact = float(
        Counter(call.name for call in expected_calls)
        == Counter(call.name for call in predicted_calls)
    )
    argument_name_coverage = _argument_name_coverage(expected_calls, predicted_calls)
    argument_value_exact = float(
        _all_arguments_match(expected_calls, predicted_calls, unordered="parallel" in category)
    )
    strict_exact = float(bool(function_name_exact) and bool(argument_value_exact))
    error = ""
    if expected_calls and not predicted_calls:
        error = "model_did_not_emit_native_tool_calls"
    elif not strict_exact:
        error = "tool_call_exact_match_failed"
    return {
        "function_name_exact_match": function_name_exact,
        "argument_name_coverage": argument_name_coverage,
        "argument_value_exact_match": argument_value_exact,
        "strict_exact_match": strict_exact,
        "error": error,
    }


def _classify_failure(
    *,
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    retrieved: list[str],
    tools_presented: list[str],
    match: dict[str, Any],
    official: dict[str, Any],
    evaluator_exact_match: float,
    response_error: str,
) -> str:
    if evaluator_exact_match == 1.0:
        return "pass"
    if response_error:
        return "model_error"
    if not predicted_calls:
        return "no_tool_call"

    expected_names = {call.name for call in expected_calls}
    presented_names = set(tools_presented)
    retrieved_names = set(retrieved)
    predicted_names = Counter(call.name for call in predicted_calls)
    expected_name_counts = Counter(call.name for call in expected_calls)

    if not expected_names.issubset(retrieved_names):
        return "retrieval_miss"
    if not expected_names.issubset(presented_names):
        return "candidate_not_present"
    if len(predicted_calls) != len(expected_calls):
        return "call_count_mismatch"
    if predicted_names != expected_name_counts:
        return "candidate_ambiguity"
    if match["argument_name_coverage"] < 1.0:
        return "argument_name_mismatch"
    if match["argument_value_exact_match"] < 1.0:
        return "argument_value_mismatch"

    official_error_type = str(official.get("official_error_type") or "")
    if official_error_type:
        return _classify_official_error_type(official_error_type)
    return "checker_mismatch"


def _ensure_failure_tags(
    row: BFCLModelCaseEvaluation,
    *,
    tools_by_name: dict[str, dict[str, Any]],
) -> None:
    if row.failure_tags:
        return
    row.failure_tags = _failure_tags(
        expected_calls=row.expected_calls,
        predicted_calls=row.predicted_calls,
        tools_by_name=tools_by_name,
        failure_category=row.failure_category,
    )


def _failure_tags(
    *,
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    tools_by_name: dict[str, dict[str, Any]],
    failure_category: str,
) -> list[str]:
    tags: list[str] = []
    if failure_category == "candidate_ambiguity" and _has_equivalent_expected_and_predicted_tool(
        expected_calls,
        predicted_calls,
        tools_by_name=tools_by_name,
    ):
        tags.append("near_duplicate_tool_surface")
    return tags


def _equivalence_adjusted_exact_match(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    *,
    tools_by_name: dict[str, dict[str, Any]],
    category: str,
    strict_exact_match: float,
) -> float:
    """Return exact-match credit after high-confidence equivalent tool surfaces.

    BFCL contains near-duplicate tools whose names differ while their function
    surface is effectively identical. This metric keeps the strict BFCL-style
    exact score intact, but also reports whether a miss is semantically the same
    tool surface with matching argument values.
    """

    if strict_exact_match == 1.0:
        return 1.0
    if len(expected_calls) != len(predicted_calls):
        return 0.0

    if "parallel" in category:
        used: set[int] = set()
        for expected in expected_calls:
            matched = False
            for index, predicted in enumerate(predicted_calls):
                if index in used:
                    continue
                if _equivalent_call_matches(expected, predicted, tools_by_name=tools_by_name):
                    used.add(index)
                    matched = True
                    break
            if not matched:
                return 0.0
        return 1.0

    return float(
        all(
            _equivalent_call_matches(expected, predicted, tools_by_name=tools_by_name)
            for expected, predicted in zip(expected_calls, predicted_calls, strict=True)
        )
    )


def _equivalent_call_matches(
    expected: ExpectedToolCall,
    predicted: PredictedToolCall,
    *,
    tools_by_name: dict[str, dict[str, Any]],
) -> bool:
    if expected.name == predicted.name:
        return _single_call_matches(expected, predicted)
    if not _tool_names_are_equivalent(expected.name, predicted.name, tools_by_name=tools_by_name):
        return False
    return _semantic_argument_values_match(expected, predicted)


def _tool_names_are_equivalent(
    left: str,
    right: str,
    *,
    tools_by_name: dict[str, dict[str, Any]],
) -> bool:
    groups = build_tool_equivalence_groups([left, right], tools_by_name)
    return any({left, right}.issubset(set(group.get("members") or [])) for group in groups)


def _semantic_argument_values_match(
    expected: ExpectedToolCall,
    predicted: PredictedToolCall,
) -> bool:
    predicted_values = list(predicted.arguments.values())
    used: set[int] = set()

    for possible_values in expected.arguments.values():
        if _allows_missing(possible_values):
            continue
        index = _find_matching_argument_value(predicted_values, possible_values, used)
        if index is None:
            return False
        used.add(index)

    for possible_values in expected.arguments.values():
        if not _allows_missing(possible_values):
            continue
        index = _find_matching_argument_value(predicted_values, possible_values, used)
        if index is not None:
            used.add(index)

    return len(used) == len(predicted_values)


def _find_matching_argument_value(
    values: list[Any],
    possible_values: list[Any],
    used: set[int],
) -> int | None:
    for index, value in enumerate(values):
        if index in used:
            continue
        if _value_matches(value, possible_values):
            return index
    return None


def _has_equivalent_expected_and_predicted_tool(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    *,
    tools_by_name: dict[str, dict[str, Any]],
) -> bool:
    expected_names = {call.name for call in expected_calls}
    predicted_names = {call.name for call in predicted_calls}
    equivalence_groups = build_tool_equivalence_groups(
        sorted(expected_names | predicted_names),
        tools_by_name,
    )
    for group in equivalence_groups:
        members = set(group.get("members") or [])
        for expected_name in expected_names - predicted_names:
            if expected_name not in members:
                continue
            if any(
                predicted_name in members for predicted_name in predicted_names - expected_names
            ):
                return True
    return False


def _classify_official_error_type(error_type: str) -> str:
    if "wrong_count" in error_type:
        return "call_count_mismatch"
    if "wrong_func_name" in error_type:
        return "candidate_ambiguity"
    if "missing_required" in error_type:
        return "argument_name_mismatch"
    if "unexpected_param" in error_type:
        return "argument_name_mismatch"
    if error_type.startswith(("type_error", "value_error")):
        return "argument_value_mismatch"
    return "official_checker_mismatch"


def _evaluate_official_predictions(
    *,
    function_descriptions: list[dict[str, Any]],
    answer_row: dict[str, Any],
    predicted_calls: list[PredictedToolCall],
    category: str,
    official_model_name: str,
) -> dict[str, Any]:
    try:
        from bfcl_eval.constants.enums import Language
        from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker
    except ImportError as exc:  # pragma: no cover - covered through availability guard
        raise ImportError(_official_checker_install_hint()) from exc

    try:
        model_output = _predicted_calls_to_bfcl_output(
            predicted_calls,
            official_model_name=official_model_name,
        )
        result = ast_checker(
            function_descriptions,
            model_output,
            list(answer_row.get("ground_truth") or []),
            Language.PYTHON,
            category,
            official_model_name,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "official_ast_exact_match": 0.0,
            "official_error_type": "official_checker_exception",
            "official_error": str(exc),
        }

    valid = bool(result.get("valid")) if isinstance(result, dict) else False
    return {
        "official_ast_exact_match": 1.0 if valid else 0.0,
        "official_error_type": str(result.get("error_type") or "")
        if isinstance(result, dict)
        else "",
        "official_error": _compact_official_error(result),
    }


def _empty_official_result() -> dict[str, Any]:
    return {
        "official_ast_exact_match": 0.0,
        "official_error_type": "",
        "official_error": "",
    }


def _predicted_calls_to_bfcl_output(
    predicted_calls: list[PredictedToolCall],
    *,
    official_model_name: str,
) -> list[dict[str, dict[str, Any]]]:
    use_safe_names = _official_model_uses_underscore_names(official_model_name)
    return [
        {_official_output_name(call.name, use_safe_names=use_safe_names): dict(call.arguments)}
        for call in predicted_calls
    ]


def _predicted_calls_to_bfcl_result(
    predicted_calls: list[PredictedToolCall],
    *,
    official_model_name: str,
    argument_format: str = "json-string",
) -> list[dict[str, Any]]:
    if argument_format not in BFCL_RESULT_ARGUMENT_FORMATS:
        msg = (
            f"Unknown BFCL result argument format: {argument_format!r}. "
            f"Expected one of {', '.join(BFCL_RESULT_ARGUMENT_FORMATS)}."
        )
        raise ValueError(msg)

    use_safe_names = _official_model_uses_underscore_names(official_model_name)
    rows: list[dict[str, Any]] = []
    for call in predicted_calls:
        name = _official_output_name(call.name, use_safe_names=use_safe_names)
        arguments = dict(call.arguments)
        value: Any
        if argument_format == "json-string":
            value = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        else:
            value = arguments
        rows.append({name: value})
    return rows


def _official_output_name(name: str, *, use_safe_names: bool) -> str:
    return re.sub(r"\.", "_", name) if use_safe_names else name


def _official_model_uses_underscore_names(official_model_name: str) -> bool:
    try:
        from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING
    except ImportError as exc:  # pragma: no cover - covered through availability guard
        if _known_underscore_model_name(official_model_name):
            return True
        raise ImportError(_official_checker_install_hint()) from exc

    key = official_model_name.replace("_", "/")
    if key not in MODEL_CONFIG_MAPPING:
        msg = (
            f"Unknown BFCL model config {official_model_name!r}. "
            "Pass a model name present in bfcl_eval.constants.model_config.MODEL_CONFIG_MAPPING, "
            f"for example {DEFAULT_OFFICIAL_MODEL_NAME!r}."
        )
        raise ValueError(msg)
    return bool(getattr(MODEL_CONFIG_MAPPING[key], "underscore_to_dot", False))


def _known_underscore_model_name(official_model_name: str) -> bool:
    normalized = official_model_name.replace("_", "/")
    return normalized == DEFAULT_OFFICIAL_MODEL_NAME or (
        normalized.startswith("qwen3-") and normalized.endswith("-FC")
    )


def _ensure_official_checker_available() -> None:
    try:
        from bfcl_eval.constants.enums import Language  # noqa: F401
        from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING  # noqa: F401
        from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker  # noqa: F401
    except ImportError as exc:
        raise ImportError(_official_checker_install_hint()) from exc


def _official_checker_install_hint() -> str:
    return (
        "Official BFCL evaluator is not installed. Install bfcl-eval and soundfile "
        "in an isolated benchmark venv, then run this module with PYTHONPATH pointing "
        "at the graph-tool-call repo."
    )


def _compact_official_error(result: Any) -> str:
    if not isinstance(result, dict) or result.get("valid"):
        return ""
    errors = result.get("error") or []
    if isinstance(errors, list):
        text = json.dumps(errors[:2], ensure_ascii=False)
    else:
        text = str(errors)
    return text[:500]


def _argument_name_coverage(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
) -> float:
    total = sum(len(call.arguments) for call in expected_calls)
    if total == 0:
        return 1.0

    covered = 0
    used: set[int] = set()
    for expected in expected_calls:
        index, score = _best_argument_name_match(expected, predicted_calls, used)
        covered += score
        if index is not None:
            used.add(index)
    return round(covered / total, 6)


def _best_argument_name_match(
    expected: ExpectedToolCall,
    predicted_calls: list[PredictedToolCall],
    used: set[int],
) -> tuple[int | None, int]:
    best_index: int | None = None
    best_score = 0
    for index, predicted in enumerate(predicted_calls):
        if index in used or predicted.name != expected.name:
            continue
        score = 0
        for arg_name, possible_values in expected.arguments.items():
            if arg_name in predicted.arguments or _allows_missing(possible_values):
                score += 1
        if score > best_score:
            best_index = index
            best_score = score
    return best_index, best_score


def _all_arguments_match(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
    *,
    unordered: bool,
) -> bool:
    if len(expected_calls) != len(predicted_calls):
        return False
    if unordered:
        return _unordered_arguments_match(expected_calls, predicted_calls)
    return all(
        _single_call_matches(expected, predicted)
        for expected, predicted in zip(expected_calls, predicted_calls, strict=True)
    )


def _unordered_arguments_match(
    expected_calls: list[ExpectedToolCall],
    predicted_calls: list[PredictedToolCall],
) -> bool:
    used: set[int] = set()
    for expected in expected_calls:
        matched = False
        for index, predicted in enumerate(predicted_calls):
            if index in used:
                continue
            if _single_call_matches(expected, predicted):
                used.add(index)
                matched = True
                break
        if not matched:
            return False
    return True


def _single_call_matches(expected: ExpectedToolCall, predicted: PredictedToolCall) -> bool:
    if expected.name != predicted.name:
        return False
    for arg_name in predicted.arguments:
        if arg_name not in expected.arguments:
            return False
    for arg_name, possible_values in expected.arguments.items():
        if arg_name not in predicted.arguments:
            if _allows_missing(possible_values):
                continue
            return False
        if not _value_matches(predicted.arguments[arg_name], possible_values):
            return False
    return True


def _allows_missing(possible_values: list[Any]) -> bool:
    return "" in possible_values


def _value_matches(value: Any, possible_values: list[Any]) -> bool:
    normalized_value = _normalize_value(value)
    return any(normalized_value == _normalize_value(possible) for possible in possible_values)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return _standardize_string(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value


def _standardize_string(input_string: str) -> str:
    return re.sub(r"[ \,\.\/\-\_\*\^]", "", input_string).lower().replace("'", '"')


def _case_tool_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for tool in row.get("function") or []:
        if isinstance(tool, dict) and tool.get("name"):
            names.append(str(tool["name"]))
    return names


def _tools_by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for row in rows:
        for tool in row.get("function") or []:
            if isinstance(tool, dict) and tool.get("name"):
                tools.setdefault(str(tool["name"]), dict(tool))
    return tools


def _case_cache_path(
    cache_dir: Path | None,
    *,
    question_row: dict[str, Any],
    category: str,
    model: str,
    llm_url: str,
    ref: str,
    top_k: int,
    tool_source: str,
    tool_choice: str,
    evaluator: str,
    official_model_name: str,
    timeout: int,
    disable_thinking: bool,
    cache_namespace: str,
    retrieval_rank_hints: bool,
    candidate_selection_guidance: bool,
    cohesive_namespace_candidates: bool,
) -> Path | None:
    if cache_dir is None:
        return None
    case_id = str(question_row.get("id") or "case")
    payload = {
        "cache_version": MODEL_CASE_CACHE_VERSION,
        "graph_tool_call_version": __version__,
        "cache_namespace": cache_namespace,
        "case_id": case_id,
        "category": category,
        "model": model,
        "llm_url": llm_url,
        "bfcl_ref": ref,
        "top_k": top_k,
        "tool_source": tool_source,
        "tool_choice": tool_choice,
        "evaluator": evaluator,
        "official_model_name": official_model_name if evaluator == "official" else "",
        "timeout": timeout,
        "disable_thinking": disable_thinking,
        "retrieval_rank_hints": retrieval_rank_hints,
        "candidate_selection_guidance": candidate_selection_guidance,
        "cohesive_namespace_candidates": cohesive_namespace_candidates,
    }
    key = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]  # noqa: S324
    safe_case_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", case_id)
    return cache_dir / category / f"{safe_case_id}_{key}.json"


def _read_case_cache(path: Path | None) -> BFCLModelCaseEvaluation | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _case_from_dict(payload)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError):
        return None


def _write_case_cache(path: Path | None, row: BFCLModelCaseEvaluation) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(row), ensure_ascii=False, indent=2), encoding="utf-8")


def _case_from_dict(payload: dict[str, Any]) -> BFCLModelCaseEvaluation:
    data = dict(payload)
    data["expected_calls"] = [
        ExpectedToolCall(name=str(row["name"]), arguments=dict(row.get("arguments") or {}))
        for row in data.get("expected_calls") or []
    ]
    data["predicted_calls"] = [
        PredictedToolCall(name=str(row["name"]), arguments=dict(row.get("arguments") or {}))
        for row in data.get("predicted_calls") or []
    ]
    data.setdefault("failure_category", "pass" if data.get("evaluator_exact_match") == 1.0 else "")
    data.setdefault("official_error_type", "")
    data.setdefault("official_error", "")
    data.setdefault("failure_tags", [])
    data.setdefault(
        "equivalence_adjusted_exact_match",
        float(data.get("evaluator_exact_match") or 0.0),
    )
    return BFCLModelCaseEvaluation(**data)


def _summarize(
    rows: list[BFCLModelCaseEvaluation],
    *,
    min_exact_match: float,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "cases": len(rows),
        "retrieval_recall_at_k": _mean(row.retrieval_recall_at_k for row in rows),
        "all_expected_tools_retrieved": _mean(row.all_expected_tools_retrieved for row in rows),
        "model_tool_call_rate": _mean(row.model_tool_call_rate for row in rows),
        "function_name_exact_match": _mean(row.function_name_exact_match for row in rows),
        "argument_name_coverage": _mean(row.argument_name_coverage for row in rows),
        "argument_value_exact_match": _mean(row.argument_value_exact_match for row in rows),
        "strict_exact_match": _mean(row.strict_exact_match for row in rows),
        "official_ast_exact_match": _mean(row.official_ast_exact_match for row in rows),
        "evaluator_exact_match": _mean(row.evaluator_exact_match for row in rows),
        "equivalence_adjusted_exact_match": _mean(
            row.equivalence_adjusted_exact_match for row in rows
        ),
        "equivalence_adjusted_exact_gain": _mean(
            row.equivalence_adjusted_exact_match - row.evaluator_exact_match for row in rows
        ),
        "equivalence_adjusted_exact_case_count": sum(
            int(row.equivalence_adjusted_exact_match > row.evaluator_exact_match) for row in rows
        ),
        "avg_input_tokens": round(_mean(row.input_tokens for row in rows), 1),
        "avg_output_tokens": round(_mean(row.output_tokens for row in rows), 1),
        "avg_latency_ms": round(_mean(row.latency_ms for row in rows), 1),
        "failure_breakdown": dict(sorted(Counter(row.failure_category for row in rows).items())),
        "failure_tag_breakdown": dict(
            sorted(Counter(tag for row in rows for tag in row.failure_tags).items())
        ),
    }
    summary["status"] = "pass" if summary["evaluator_exact_match"] >= min_exact_match else "fail"
    return summary


def _mean(values: Any) -> float:
    vals = [float(value) for value in values]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 6)


def bfcl_result_rows(
    report: dict[str, Any],
    *,
    official_model_name: str | None = None,
    argument_format: str = "json-string",
) -> dict[str, list[dict[str, Any]]]:
    """Return official BFCL result rows grouped by category."""
    selected_model_name = official_model_name or str(
        report.get("official_model_name") or DEFAULT_OFFICIAL_MODEL_NAME
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for category in report.get("categories") or []:
        category_name = str(category.get("category") or "")
        if not category_name:
            continue
        rows: list[dict[str, Any]] = []
        for case in category.get("cases") or []:
            predicted_calls = _predicted_calls_from_payload(case.get("predicted_calls") or [])
            rows.append(
                {
                    "id": str(case.get("case_id") or ""),
                    "result": _predicted_calls_to_bfcl_result(
                        predicted_calls,
                        official_model_name=selected_model_name,
                        argument_format=argument_format,
                    ),
                    "input_token_count": int(case.get("input_tokens") or 0),
                    "output_token_count": int(case.get("output_tokens") or 0),
                    "latency": round(float(case.get("latency_ms") or 0.0) / 1000, 6),
                    "graph_tool_call": {
                        "version": str(report.get("graph_tool_call_version") or __version__),
                        "tool_source": str(report.get("tool_source") or case.get("tool_source")),
                        "top_k": int(report.get("top_k") or 0),
                        "retrieved": list(case.get("retrieved") or []),
                        "tools_presented": list(case.get("tools_presented") or []),
                        "failure_category": str(case.get("failure_category") or ""),
                        "failure_tags": list(case.get("failure_tags") or []),
                        "evaluator_exact_match": float(case.get("evaluator_exact_match") or 0.0),
                        "equivalence_adjusted_exact_match": float(
                            case.get("equivalence_adjusted_exact_match") or 0.0
                        ),
                    },
                }
            )
        grouped[category_name] = rows
    return grouped


def write_bfcl_result_files(
    report: dict[str, Any],
    output_dir: Path,
    *,
    official_model_name: str | None = None,
    argument_format: str = "json-string",
) -> list[Path]:
    """Write BFCL-compatible result JSONL files and return the written paths."""
    selected_model_name = official_model_name or str(
        report.get("official_model_name") or DEFAULT_OFFICIAL_MODEL_NAME
    )
    grouped = bfcl_result_rows(
        report,
        official_model_name=selected_model_name,
        argument_format=argument_format,
    )
    written: list[Path] = []
    for category, rows in grouped.items():
        path = output_dir / selected_model_name / "non_live" / f"BFCL_v4_{category}_result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        written.append(path)
    return written


def _predicted_calls_from_payload(rows: list[Any]) -> list[PredictedToolCall]:
    predicted: list[PredictedToolCall] = []
    for row in rows:
        if isinstance(row, PredictedToolCall):
            predicted.append(row)
        elif isinstance(row, dict):
            predicted.append(
                PredictedToolCall(
                    name=str(row.get("name") or ""),
                    arguments=dict(row.get("arguments") or {}),
                )
            )
    return predicted


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(report["benchmark"])
    print(
        f"model={report['model']} methodology={report['methodology']} "
        f"source={report['source']} ref={report['bfcl_ref']} "
        f"tool_source={report['tool_source']} evaluator={report['evaluator']} "
        f"status={summary['status']}"
    )
    print(
        "retrieval@K={retrieval:.2f} call_rate={call:.2f} "
        "func_exact={func:.2f} arg_names={arg_names:.2f} "
        "arg_values={arg_values:.2f} strict={strict:.2f} exact={exact:.2f} "
        "equiv_exact={equiv_exact:.2f} "
        "latency={latency:.1f}ms".format(
            retrieval=summary["retrieval_recall_at_k"],
            call=summary["model_tool_call_rate"],
            func=summary["function_name_exact_match"],
            arg_names=summary["argument_name_coverage"],
            arg_values=summary["argument_value_exact_match"],
            strict=summary["strict_exact_match"],
            exact=summary["evaluator_exact_match"],
            equiv_exact=summary["equivalence_adjusted_exact_match"],
            latency=summary["avg_latency_ms"],
        )
    )
    breakdown = summary.get("failure_breakdown") or {}
    if breakdown:
        formatted = ", ".join(f"{name}={count}" for name, count in breakdown.items())
        print(f"failure_breakdown: {formatted}")
    tag_breakdown = summary.get("failure_tag_breakdown") or {}
    if tag_breakdown:
        formatted = ", ".join(f"{name}={count}" for name, count in tag_breakdown.items())
        print(f"failure_tag_breakdown: {formatted}")
    for category in report["categories"]:
        cat = category["summary"]
        print(
            "  {name}: cases={cases} tools={tools} retrieval@K={retrieval:.2f} "
            "strict={strict:.2f} exact={exact:.2f} equiv_exact={equiv_exact:.2f} "
            "call_rate={call:.2f} failures={failures}".format(
                name=category["category"],
                cases=category["case_count"],
                tools=category["corpus_tool_count"],
                retrieval=cat["retrieval_recall_at_k"],
                strict=cat["strict_exact_match"],
                exact=cat["evaluator_exact_match"],
                equiv_exact=cat["equivalence_adjusted_exact_match"],
                call=cat["model_tool_call_rate"],
                failures=_format_failure_breakdown(cat.get("failure_breakdown") or {}),
            )
        )


def _format_failure_breakdown(breakdown: dict[str, int]) -> str:
    if not breakdown:
        return "-"
    return ",".join(f"{name}:{count}" for name, count in breakdown.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--llm-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument(
        "--categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated BFCL categories.",
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
    parser.add_argument("--tool-source", choices=["retrieved", "row"], default="retrieved")
    parser.add_argument("--tool-choice", choices=["required", "auto"], default="required")
    parser.add_argument(
        "--evaluator",
        choices=["local", "official"],
        default="local",
        help="Use the local BFCL-compatible matcher or the optional official bfcl-eval checker.",
    )
    parser.add_argument(
        "--official-model-name",
        default=DEFAULT_OFFICIAL_MODEL_NAME,
        help="BFCL model config name used by the official checker for function-name conversion.",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--cache-namespace",
        default="",
        help=(
            "Optional cache namespace. Use a different value for independent repeated "
            "model runs that should not reuse prior case outputs."
        ),
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore existing case cache entries and overwrite them with fresh model calls.",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="Pass chat-template thinking disable options for Qwen/vLLM-style reasoning models.",
    )
    parser.add_argument(
        "--retrieval-rank-hints",
        action="store_true",
        help=(
            "For retrieved tool-source runs, prefix tool descriptions with graph retrieval rank "
            "hints. Use as an ablation for candidate ambiguity."
        ),
    )
    parser.add_argument(
        "--candidate-selection-guidance",
        action="store_true",
        help=(
            "Add deterministic candidate-selection guidance to the system prompt. "
            "Use as an ablation for call-count mismatch and sibling ambiguity."
        ),
    )
    parser.add_argument(
        "--cohesive-namespace-candidates",
        action="store_true",
        help=(
            "For retrieved multi-action queries, present only candidate tools from dotted "
            "namespaces that contribute at least two retrieved tools. Use as an ablation for "
            "sibling ambiguity."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of BFCL cases to evaluate concurrently within each category.",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Print cache/model-call progress to stderr while cases are running.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Progress print interval in completed cases.",
    )
    parser.add_argument("--min-exact-match", type=float, default=0.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the full graph-tool-call benchmark report JSON.",
    )
    parser.add_argument(
        "--bfcl-result-dir",
        type=Path,
        default=None,
        help=(
            "Optional root directory for BFCL-compatible result JSONL files. "
            "Files are written below <dir>/<official-model-name>/non_live/."
        ),
    )
    parser.add_argument(
        "--bfcl-result-argument-format",
        choices=BFCL_RESULT_ARGUMENT_FORMATS,
        default="json-string",
        help="Use json-string for BFCL OpenAI/Qwen FC handlers, decoded for direct AST input.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_model_benchmark(
            model=args.model,
            llm_url=args.llm_url,
            categories=_parse_categories(args.categories),
            data_root=args.data_root,
            ref=args.ref,
            top_k=args.top_k,
            limit=args.limit,
            case_ids=load_case_ids(args.case_ids_file),
            tool_source=args.tool_source,
            tool_choice=args.tool_choice,
            evaluator=args.evaluator,
            official_model_name=args.official_model_name,
            cache_dir=args.cache_dir,
            cache_namespace=args.cache_namespace,
            refresh_cache=args.refresh_cache,
            timeout=args.timeout,
            disable_thinking=args.disable_thinking,
            min_exact_match=args.min_exact_match,
            concurrency=args.concurrency,
            progress=args.progress,
            progress_every=args.progress_every,
            retrieval_rank_hints=args.retrieval_rank_hints,
            candidate_selection_guidance=args.candidate_selection_guidance,
            cohesive_namespace_candidates=args.cohesive_namespace_candidates,
        )
    except ImportError as exc:
        parser.error(str(exc))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.bfcl_result_dir:
        write_bfcl_result_files(
            report,
            args.bfcl_result_dir,
            official_model_name=args.official_model_name,
            argument_format=args.bfcl_result_argument_format,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
