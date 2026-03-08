"""LLM runner for end-to-end tool calling benchmarks.

Calls Ollama API with tool definitions and returns tool call results.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    """Result of a single LLM tool-calling invocation."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    raw_content: str = ""
    error: str | None = None


def tool_schema_to_openai(tool) -> dict:
    """Convert ToolSchema to OpenAI function-calling format for Ollama."""
    params: dict = {"type": "object", "properties": {}, "required": []}
    for p in tool.parameters:
        prop: dict = {"type": p.type, "description": p.description}
        if p.enum:
            prop["enum"] = p.enum
        params["properties"][p.name] = prop
        if p.required:
            params["required"].append(p.name)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": params,
        },
    }


def call_ollama(
    model: str,
    query: str,
    tools: list[dict],
    *,
    ollama_url: str = "http://localhost:11434/api/chat",
    num_ctx: int = 8192,
    timeout: int = 120,
    system_prompt: str | None = None,
) -> LLMResult:
    """Call Ollama chat API with tool definitions.

    Parameters
    ----------
    model:
        Ollama model name (e.g. "qwen3.5:4b").
    query:
        User query string.
    tools:
        List of tools in OpenAI function-calling format.
    ollama_url:
        Ollama API endpoint.
    num_ctx:
        Context window size.
    timeout:
        Request timeout in seconds.
    system_prompt:
        Optional system prompt.

    Returns
    -------
    LLMResult
        Contains tool calls, token counts, latency.
    """
    if system_prompt is None:
        system_prompt = (
            "You are an API assistant. Use the provided tools to help the user. "
            "Always call the most appropriate tool. Do not ask follow-up questions."
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": num_ctx},
    }
    if tools:
        payload["tools"] = tools

    result = LLMResult()

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            ollama_url, data=data, headers={"Content-Type": "application/json"}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        result.latency = time.perf_counter() - t0

        result.input_tokens = body.get("prompt_eval_count", 0)
        result.output_tokens = body.get("eval_count", 0)

        msg = body.get("message", {})
        result.raw_content = msg.get("content", "")
        result.tool_calls = msg.get("tool_calls", [])

    except Exception as e:  # noqa: BLE001
        result.error = str(e)

    return result


def call_openai_compatible(
    model: str,
    query: str,
    tools: list[dict],
    *,
    base_url: str = "http://localhost:8002/v1",
    timeout: int = 120,
    system_prompt: str | None = None,
) -> LLMResult:
    """Call OpenAI-compatible API (llama.cpp, vLLM, etc.) with tool definitions.

    Parameters
    ----------
    model:
        Model name as registered on the server.
    query:
        User query string.
    tools:
        List of tools in OpenAI function-calling format.
    base_url:
        Server base URL (e.g. "http://localhost:8002/v1").
    timeout:
        Request timeout in seconds.
    system_prompt:
        Optional system prompt.

    Returns
    -------
    LLMResult
        Contains tool calls, token counts, latency.
    """
    if system_prompt is None:
        system_prompt = (
            "You are an API assistant. Use the provided tools to help the user. "
            "Always call the most appropriate tool. Do not ask follow-up questions."
        )

    url = f"{base_url.rstrip('/')}/chat/completions"

    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
    }
    if tools:
        payload["tools"] = tools

    result = LLMResult()

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        result.latency = time.perf_counter() - t0

        usage = body.get("usage", {})
        result.input_tokens = usage.get("prompt_tokens", 0)
        result.output_tokens = usage.get("completion_tokens", 0)

        choice = body.get("choices", [{}])[0]
        msg = choice.get("message", {})
        result.raw_content = msg.get("content", "")
        result.tool_calls = msg.get("tool_calls", [])

    except Exception as e:  # noqa: BLE001
        result.error = str(e)

    return result


def tools_to_openai_format(tool_schemas) -> list[dict]:
    """Convert ToolSchema objects to OpenAI function-calling format for Ollama.

    Parameters
    ----------
    tool_schemas:
        List of ToolSchema objects.

    Returns
    -------
    list[dict]
        Tools in OpenAI function-calling format.
    """
    return [tool_schema_to_openai(t) for t in tool_schemas]


def extract_tool_name(result: LLMResult) -> str | None:
    """Extract the first tool name from an LLM result.

    Parameters
    ----------
    result:
        LLM result from call_ollama.

    Returns
    -------
    str | None
        Tool name or None if no tool call was made.
    """
    if not result.tool_calls:
        return None
    tc = result.tool_calls[0]
    fn = tc.get("function", {})
    return fn.get("name")
