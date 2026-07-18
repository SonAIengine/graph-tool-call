from __future__ import annotations

from benchmarks.xgen_tool_graph import llm_loop
from benchmarks.xgen_tool_graph.llm_loop import (
    ChatResponse,
    _extract_search_call,
    extract_json_object,
)


def test_extract_native_search_tool_call():
    response = ChatResponse(
        tool_calls=[
            {
                "function": {
                    "name": "search_tools",
                    "arguments": '{"query": "상품 상세"}',
                }
            }
        ]
    )

    assert _extract_search_call(response, protocol="native") == {"query": "상품 상세"}


def test_extract_prompted_search_tool_call():
    response = ChatResponse(
        content='{"tool_call":{"name":"search_tools","arguments":{"query":"배송 조회"}}}'
    )

    assert _extract_search_call(response, protocol="prompted") == {"query": "배송 조회"}


def test_extract_json_object_from_noisy_model_output():
    assert extract_json_object(
        'Here is the result: {"target_tool": "getProductDetail", "plan": ["searchProducts"]}'
    ) == {"target_tool": "getProductDetail", "plan": ["searchProducts"]}


def test_openai_compatible_can_disable_qwen_thinking(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }

    monkeypatch.setattr(llm_loop, "_post_json", fake_post_json)

    response = llm_loop._chat_openai_compatible(
        model="qwen3.6-27b",
        base_url="http://127.0.0.1:8000/v1",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        timeout=7,
        disable_thinking=True,
    )

    assert response.content == '{"ok": true}'
    assert captured["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["timeout"] == 7


def test_ollama_chat_path_forwards_disable_thinking(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {
            "message": {
                "content": '{"target_tool": "searchProducts"}',
                "tool_calls": [{"function": {"name": "search_tools", "arguments": "{}"}}],
            },
            "prompt_eval_count": 4,
            "eval_count": 5,
        }

    monkeypatch.setattr(llm_loop, "_post_json", fake_post_json)

    response = llm_loop._chat(
        model="qwen3:4b",
        llm_url="http://localhost:11434/api/chat",
        messages=[{"role": "user", "content": "상품 검색"}],
        tools=[{"type": "function", "function": {"name": "search_tools"}}],
        timeout=13,
        disable_thinking=True,
    )

    assert response.content == '{"target_tool": "searchProducts"}'
    assert response.input_tokens == 4
    assert response.output_tokens == 5
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["think"] is False
    assert captured["timeout"] == 13
