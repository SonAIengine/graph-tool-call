"""Token savings demo — shows how graph-tool-call reduces LLM input tokens."""

from __future__ import annotations

import json
import sys

import tiktoken

from graph_tool_call import ToolGraph
from graph_tool_call.langchain.tools import tool_schema_to_openai_function


def count_tokens(tools_json: list[dict], model: str = "gpt-4o") -> int:
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(json.dumps(tools_json)))


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/specs/k8s_core_v1.json"
    query = sys.argv[2] if len(sys.argv) > 2 else "delete a pod"
    top_k = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    # Build graph
    tg = ToolGraph()
    tg.ingest_openapi(source)
    all_tools = list(tg.tools.values())

    # All tools → OpenAI format
    all_openai = [tool_schema_to_openai_function(t) for t in all_tools]
    all_tokens = count_tokens(all_openai)

    # Retrieve top-K → OpenAI format
    results = tg.retrieve(query, top_k=top_k)
    top_openai = [tool_schema_to_openai_function(t) for t in results]
    top_tokens = count_tokens(top_openai)

    reduction = (1 - top_tokens / all_tokens) * 100

    print(f'Query: "{query}"')
    print(f"Source: {source}\n")
    print(f"  All tools:      {len(all_tools):>4} tools → {all_tokens:>6,} tokens")
    print(f"  graph-tool-call: {top_k:>3} tools → {top_tokens:>6,} tokens")
    print(f"  Token reduction: {reduction:.1f}%")
    print(f"\nSelected tools:")
    for i, t in enumerate(results, 1):
        print(f"  {i}. {t.name}")


if __name__ == "__main__":
    main()
