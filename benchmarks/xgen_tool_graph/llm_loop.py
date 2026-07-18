"""BFCL-style LLM-in-the-loop benchmark for XGEN tool graph search.

This benchmark gives the model a single search function backed by
graph-tool-call. The model must call that function, inspect the returned
candidates, and then emit a small JSON answer that can be exact-matched.

It complements ``benchmarks.xgen_tool_graph.run``:

* ``run`` measures the deterministic engine contract directly.
* ``llm_loop`` measures whether an actual model can use the search tool.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.metrics import recall_at_k
from benchmarks.xgen_tool_graph.run import (
    DEFAULT_CASES_PATH,
    DEFAULT_SPEC_PATH,
    _binding_accuracy,
    build_benchmark_graph,
    load_json,
)
from graph_tool_call.graphify import expand_candidates_with_producers, retrieve_graphify
from graph_tool_call.plan import PathSynthesizer, Plan

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:4b"
SEARCH_TOOL_NAME = "search_tools"


@dataclass
class ChatResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class LLMCaseEvaluation:
    case_id: str
    query: str
    expected_target: str
    search_called: bool
    search_query: str
    retrieved: list[str]
    candidates: list[str]
    search_target_recall_at_k: float
    candidate_plan_coverage: float
    final_target: str
    final_plan: list[str]
    final_target_accuracy: float
    final_plan_exact_match: float
    final_plan_step_recall: float
    final_binding_accuracy: float
    tool_call_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: float
    error: str = ""
    raw_final: str = ""


def run_llm_benchmark(
    *,
    model: str = DEFAULT_MODEL,
    llm_url: str = DEFAULT_OLLAMA_URL,
    spec_path: Path = DEFAULT_SPEC_PATH,
    cases_path: Path = DEFAULT_CASES_PATH,
    limit: int | None = None,
    top_k: int | None = None,
    token_budget: int | None = None,
    timeout: int = 180,
    protocol: str = "native",
    disable_thinking: bool = False,
) -> dict[str, Any]:
    """Run model-in-the-loop search benchmark."""
    cases_doc = load_json(cases_path)
    configured_top_k = int(top_k or cases_doc.get("top_k") or 5)
    configured_budget = int(token_budget or cases_doc.get("token_budget") or 2000)
    tg, graph_payload, _raw_spec = build_benchmark_graph(spec_path=spec_path)
    context_defaults = dict(cases_doc.get("context_defaults") or {})
    cases = list(cases_doc.get("cases") or [])
    if limit is not None:
        cases = cases[: max(0, limit)]

    rows = [
        evaluate_llm_case(
            case,
            model=model,
            llm_url=llm_url,
            protocol=protocol,
            tg=tg,
            graph_payload=graph_payload,
            context_defaults=context_defaults,
            top_k=configured_top_k,
            token_budget=configured_budget,
            timeout=timeout,
            disable_thinking=disable_thinking,
        )
        for case in cases
    ]

    return {
        "benchmark": f"{cases_doc.get('name')} LLM Loop",
        "methodology": "bfcl_style_model_in_the_loop",
        "model": model,
        "llm_url": _redacted_url(llm_url),
        "protocol": protocol,
        "disable_thinking": disable_thinking,
        "top_k": configured_top_k,
        "token_budget": configured_budget,
        "cases": [asdict(row) for row in rows],
        "summary": _summarize(rows),
    }


def evaluate_llm_case(
    case: dict[str, Any],
    *,
    model: str,
    llm_url: str,
    protocol: str,
    tg: Any,
    graph_payload: dict[str, Any],
    context_defaults: dict[str, Any],
    top_k: int,
    token_budget: int,
    timeout: int,
    disable_thinking: bool,
) -> LLMCaseEvaluation:
    expected_target = str(case["expected_target"])
    expected_plan = list(case.get("expected_plan") or [])
    expected_bindings = dict(case.get("expected_bindings") or {})
    query = str(case["query"])

    started = time.perf_counter()
    first = _call_model_for_search(
        model=model,
        llm_url=llm_url,
        query=query,
        protocol=protocol,
        timeout=timeout,
        disable_thinking=disable_thinking,
    )
    tool_call = _extract_search_call(first, protocol=protocol)
    if not tool_call:
        return LLMCaseEvaluation(
            case_id=str(case["id"]),
            query=query,
            expected_target=expected_target,
            search_called=False,
            search_query="",
            retrieved=[],
            candidates=[],
            search_target_recall_at_k=0.0,
            candidate_plan_coverage=0.0,
            final_target="",
            final_plan=[],
            final_target_accuracy=0.0,
            final_plan_exact_match=0.0,
            final_plan_step_recall=0.0,
            final_binding_accuracy=0.0,
            tool_call_count=len(first.tool_calls),
            input_tokens=first.input_tokens,
            output_tokens=first.output_tokens,
            latency_ms=round(first.latency_ms, 3),
            error=first.error or "model_did_not_call_search_tools",
            raw_final=first.content,
        )

    search_query = str(tool_call.get("query") or query)
    search_result = _execute_search_tool(
        search_query,
        tg=tg,
        graph_payload=graph_payload,
        top_k=top_k,
        token_budget=token_budget,
    )
    final = _call_model_for_final(
        model=model,
        llm_url=llm_url,
        query=query,
        search_result=search_result,
        protocol=protocol,
        timeout=timeout,
        disable_thinking=disable_thinking,
    )
    final_payload = extract_json_object(final.content)
    final_target = str(final_payload.get("target_tool") or "")
    final_plan = [str(v) for v in final_payload.get("plan") or []]
    plan = _synthesize_plan(
        graph_payload,
        target=expected_target,
        entities=dict(case.get("entities") or {}),
        goal=query,
        context_defaults=context_defaults,
    )

    retrieved = [str(v) for v in search_result.get("retrieved") or []]
    candidates = [str(v) for v in search_result.get("candidates") or []]
    latency_ms = (time.perf_counter() - started) * 1000
    final_plan_recall = recall_at_k(final_plan, set(expected_plan), len(final_plan))

    return LLMCaseEvaluation(
        case_id=str(case["id"]),
        query=query,
        expected_target=expected_target,
        search_called=True,
        search_query=search_query,
        retrieved=retrieved,
        candidates=candidates,
        search_target_recall_at_k=recall_at_k(retrieved, {expected_target}, top_k),
        candidate_plan_coverage=recall_at_k(candidates, set(expected_plan), len(candidates)),
        final_target=final_target,
        final_plan=final_plan,
        final_target_accuracy=1.0 if final_target == expected_target else 0.0,
        final_plan_exact_match=1.0 if final_plan == expected_plan else 0.0,
        final_plan_step_recall=final_plan_recall,
        final_binding_accuracy=_binding_accuracy(plan, expected_bindings),
        tool_call_count=1 + len(final.tool_calls),
        input_tokens=first.input_tokens + final.input_tokens,
        output_tokens=first.output_tokens + final.output_tokens,
        latency_ms=round(latency_ms, 3),
        error=final.error,
        raw_final=final.content,
    )


def _execute_search_tool(
    query: str,
    *,
    tg: Any,
    graph_payload: dict[str, Any],
    top_k: int,
    token_budget: int,
) -> dict[str, Any]:
    retrieval = retrieve_graphify(
        tg,
        query,
        top_k=top_k,
        depth=2,
        token_budget=token_budget,
        include_evidence=True,
    )
    retrieved = [str(row["name"]) for row in retrieval.get("results") or []]
    candidates = expand_candidates_with_producers(
        retrieved,
        graph_payload["tools"],
        max_producers_per_field=3,
    )
    tools_by_name = graph_payload["tools"]
    return {
        "query": query,
        "retrieved": retrieved,
        "candidates": candidates,
        "results": [
            _candidate_summary(name, tools_by_name, expanded_from=_expanded_from(name, retrieval))
            for name in candidates
        ],
        "stats": retrieval.get("stats") or {},
    }


def _candidate_summary(
    name: str,
    tools_by_name: dict[str, Any],
    *,
    expanded_from: str = "",
) -> dict[str, Any]:
    tool = tools_by_name.get(name) or {}
    metadata = tool.get("metadata") or {}
    ai = metadata.get("ai_metadata") or {}
    row = {
        "name": name,
        "description": tool.get("description") or "",
        "canonical_action": ai.get("canonical_action") or "",
        "primary_resource": ai.get("primary_resource") or "",
        "when_to_use": ai.get("when_to_use") or "",
        "consumes": _compact_fields(metadata.get("consumes") or []),
        "produces": _compact_fields(metadata.get("produces") or []),
    }
    if expanded_from:
        row["expanded_from"] = expanded_from
    return row


def _compact_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        compact.append(
            {
                "field_name": row.get("field_name") or "",
                "semantic_tag": row.get("semantic_tag") or "",
                "kind": row.get("kind") or "data",
                "required": bool(row.get("required")),
                **({"json_path": row.get("json_path")} if row.get("json_path") else {}),
            }
        )
    return compact


def _expanded_from(name: str, retrieval: dict[str, Any]) -> str:
    for row in retrieval.get("results") or []:
        if row.get("name") == name:
            return str(row.get("expanded_from") or "")
    return ""


def _synthesize_plan(
    graph_payload: dict[str, Any],
    *,
    target: str,
    entities: dict[str, Any],
    goal: str,
    context_defaults: dict[str, Any],
) -> Plan:
    return PathSynthesizer(graph_payload, context_defaults=context_defaults).synthesize(
        target=target,
        entities=entities,
        goal=goal,
    )


def _call_model_for_search(
    *,
    model: str,
    llm_url: str,
    query: str,
    protocol: str,
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    system = (
        "You are evaluating tool search. You must use search_tools before answering. "
        "Do not answer from memory."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _search_instruction(query, protocol=protocol)},
    ]
    tools = [_search_tool_schema()] if protocol == "native" else []
    return _chat(
        model=model,
        llm_url=llm_url,
        messages=messages,
        tools=tools,
        timeout=timeout,
        disable_thinking=disable_thinking,
    )


def _call_model_for_final(
    *,
    model: str,
    llm_url: str,
    query: str,
    search_result: dict[str, Any],
    protocol: str,
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    system = (
        "Use only the search tool result. Respond with one JSON object and no prose. "
        'Schema: {"target_tool": string, "plan": [string], "bindings": object}. '
        "`target_tool` is the final API operation that satisfies the user request, "
        "not the first prerequisite operation. `plan` must be an ordered list of "
        "tool names from the search result. Include prerequisite producer tools "
        "before a target when the target consumes fields that another candidate "
        "produces. Continue this dependency chain until the target inputs are "
        "available from user input, context, or previous tools."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
        {
            "role": "tool" if protocol == "native" else "user",
            "name": SEARCH_TOOL_NAME,
            "content": json.dumps(search_result, ensure_ascii=False),
        },
        {
            "role": "user",
            "content": (
                "Choose the final target tool and complete ordered plan from the tool result. "
                "Use consumes/produces fields to include prerequisite producers. "
                "Return only JSON with tool names."
            ),
        },
    ]
    return _chat(
        model=model,
        llm_url=llm_url,
        messages=messages,
        tools=[],
        timeout=timeout,
        disable_thinking=disable_thinking,
    )


def _search_instruction(query: str, *, protocol: str) -> str:
    if protocol == "native":
        return query
    return (
        "Call search_tools by returning only this JSON shape: "
        '{"tool_call":{"name":"search_tools","arguments":{"query":"..."}}}. '
        f"User query: {query}"
    )


def _search_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": SEARCH_TOOL_NAME,
            "description": "Search available API tools by natural language query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query."}
                },
                "required": ["query"],
            },
        },
    }


def _chat(
    *,
    model: str,
    llm_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    if "/v1" in llm_url.rstrip("/"):
        return _chat_openai_compatible(
            model=model,
            base_url=llm_url,
            messages=messages,
            tools=tools,
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
        "think": False,
        "options": {"num_ctx": 4096, "num_predict": 512, "temperature": 0},
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


def _chat_openai_compatible(
    *,
    model: str,
    base_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout: int,
    disable_thinking: bool,
) -> ChatResponse:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": 512,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
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


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode())


def _extract_search_call(response: ChatResponse, *, protocol: str) -> dict[str, Any] | None:
    if protocol == "native":
        for call in response.tool_calls:
            fn = call.get("function") or {}
            if fn.get("name") != SEARCH_TOOL_NAME:
                continue
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if isinstance(args, dict):
                return {"query": args.get("query") or ""}
        return None

    payload = extract_json_object(response.content)
    tool_call = payload.get("tool_call") if isinstance(payload, dict) else {}
    if not isinstance(tool_call, dict) or tool_call.get("name") != SEARCH_TOOL_NAME:
        return None
    args = tool_call.get("arguments") or {}
    return args if isinstance(args, dict) else None


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from model output."""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _summarize(rows: list[LLMCaseEvaluation]) -> dict[str, float | int | str]:
    summary: dict[str, float | int | str] = {
        "cases": len(rows),
        "search_tool_call_rate": _mean(1.0 if r.search_called else 0.0 for r in rows),
        "search_target_recall_at_k": _mean(r.search_target_recall_at_k for r in rows),
        "candidate_plan_coverage": _mean(r.candidate_plan_coverage for r in rows),
        "final_target_accuracy": _mean(r.final_target_accuracy for r in rows),
        "final_plan_exact_match": _mean(r.final_plan_exact_match for r in rows),
        "final_plan_step_recall": _mean(r.final_plan_step_recall for r in rows),
        "final_binding_accuracy": _mean(r.final_binding_accuracy for r in rows),
        "avg_tool_calls": _mean(r.tool_call_count for r in rows),
        "avg_input_tokens": round(_mean(r.input_tokens for r in rows), 1),
        "avg_output_tokens": round(_mean(r.output_tokens for r in rows), 1),
        "avg_latency_ms": round(_mean(r.latency_ms for r in rows), 1),
    }
    summary["status"] = (
        "pass"
        if summary["search_tool_call_rate"] == 1.0
        and summary["final_target_accuracy"] >= 0.8
        and summary["final_plan_step_recall"] >= 0.8
        else "fail"
    )
    return summary


def _mean(values: Any) -> float:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 6)


def _redacted_url(url: str) -> str:
    return re.sub(r"://([^/@]+)@", "://***@", url)


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"{report['benchmark']}")
    print(
        f"model={report['model']} protocol={report['protocol']} "
        f"disable_thinking={str(report.get('disable_thinking', False)).lower()} "
        f"status={summary['status']}"
    )
    print(
        "search_call={search:.2f} target@K={target:.2f} final_target={final:.2f} "
        "plan_exact={plan:.2f} step_recall={step:.2f} latency={latency:.1f}ms".format(
            search=summary["search_tool_call_rate"],
            target=summary["search_target_recall_at_k"],
            final=summary["final_target_accuracy"],
            plan=summary["final_plan_exact_match"],
            step=summary["final_plan_step_recall"],
            latency=summary["avg_latency_ms"],
        )
    )
    for row in report["cases"]:
        marker = "OK" if row["final_target_accuracy"] == 1.0 else "FAIL"
        print(
            f"  [{marker}] {row['case_id']}: search_called={row['search_called']} "
            f"target={row['final_target'] or '-'} expected={row['expected_target']} "
            f"error={row['error'] or '-'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--llm-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--token-budget", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--protocol", choices=["native", "prompted"], default="native")
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="Pass chat-template thinking disable options for Qwen/vLLM-style reasoning models.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_llm_benchmark(
        model=args.model,
        llm_url=args.llm_url,
        spec_path=args.spec,
        cases_path=args.cases,
        limit=args.limit,
        top_k=args.top_k,
        token_budget=args.token_budget,
        timeout=args.timeout,
        protocol=args.protocol,
        disable_thinking=args.disable_thinking,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if report["summary"]["status"] == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
