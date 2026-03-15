"""Token savings demo — visual before/after comparison."""

from __future__ import annotations

import json
import sys

import tiktoken

from graph_tool_call import ToolGraph
from graph_tool_call.langchain.tools import tool_schema_to_openai_function

# ANSI colors
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BAR_FULL = "█"
BAR_EMPTY = "░"


def count_tokens(tools_json: list[dict], model: str = "gpt-4o") -> int:
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(json.dumps(tools_json)))


def bar(ratio: float, width: int = 40) -> str:
    filled = max(1, int(ratio * width))  # at least 1 block visible
    return f"{RED}{BAR_FULL * filled}{DIM}{BAR_EMPTY * (width - filled)}{RESET}"


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/specs/k8s_core_v1.json"
    query = sys.argv[2] if len(sys.argv) > 2 else "delete a pod"
    top_k = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    tg = ToolGraph()
    tg.ingest_openapi(source)
    all_tools = list(tg.tools.values())

    all_openai = [tool_schema_to_openai_function(t) for t in all_tools]
    all_tokens = count_tokens(all_openai)

    results = tg.retrieve(query, top_k=top_k)
    top_openai = [tool_schema_to_openai_function(t) for t in results]
    top_tokens = count_tokens(top_openai)

    reduction = (1 - top_tokens / all_tokens) * 100

    print()
    print(f'  {CYAN}Query:{RESET} {BOLD}"{query}"{RESET}')
    print()
    print(f"  {DIM}Before{RESET}  {bar(1.0)}  {RED}{all_tokens:,} tokens{RESET}  ({len(all_tools)} tools)")
    print(f"  {BOLD}After{RESET}   {bar(top_tokens / all_tokens)}  {GREEN}{top_tokens:,} tokens{RESET}  ({top_k} tools)")
    print()
    print(f"  {BOLD}{GREEN}→ {reduction:.0f}% fewer tokens{RESET}")
    print()
    print(f"  {DIM}Selected tools:{RESET}")
    for i, t in enumerate(results, 1):
        print(f"    {YELLOW}{i}.{RESET} {t.name}")
    print()


if __name__ == "__main__":
    main()
