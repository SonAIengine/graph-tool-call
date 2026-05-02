"""Bonsai-8B (1-bit Q1_0) tool calling 능력 테스트.

3가지 테스트:
1. SearchLLM 통합 (query expansion / intent decomposition)
2. OpenAI function calling format (tools parameter)
3. graph-tool-call retrieve + LLM 조합
"""
# ruff: noqa: E501

from __future__ import annotations

import json
import time
import urllib.request

BASE_URL = "http://localhost:8080/v1"
MODEL = "Bonsai-8B.gguf"

# ── 테스트용 도구 정의 ──────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to a recipient",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Email body content"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search for products in the catalog",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "category": {"type": "string", "description": "Product category filter"},
                    "max_price": {"type": "number", "description": "Maximum price filter"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Create a new order for a product",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Product ID to order"},
                    "quantity": {"type": "integer", "description": "Number of items"},
                    "shipping_address": {"type": "string", "description": "Delivery address"},
                },
                "required": ["product_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel an existing order",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order ID to cancel"},
                    "reason": {"type": "string", "description": "Cancellation reason"},
                },
                "required": ["order_id"],
            },
        },
    },
]


def chat(messages: list[dict], tools: list[dict] | None = None, **kwargs) -> dict:
    """OpenAI 호환 API 호출."""
    payload: dict = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 512,
        **kwargs,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(label: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    mark = "[v]" if passed else "[x]"
    print(f"  {mark} {label}: {status}")
    if detail:
        print(f"      -> {detail}")


# ── TEST 1: SearchLLM 통합 ──────────────────────────────────────────


def test_search_llm():
    """graph-tool-call의 OpenAICompatibleSearchLLM으로 query expansion 테스트."""
    print_header("TEST 1: SearchLLM Query Expansion & Intent Decomposition")

    from graph_tool_call.retrieval.search_llm import OpenAICompatibleSearchLLM

    llm = OpenAICompatibleSearchLLM(
        model=MODEL,
        base_url=BASE_URL,
        api_key="none",
    )

    # 1a. Query Expansion
    print("\n  [Query Expansion]")
    queries = [
        "파일을 읽고 내용을 수정해서 저장하고 싶어",
        "search for cheap laptops and order one",
        "주문 취소하고 환불 처리해줘",
    ]
    for q in queries:
        t0 = time.time()
        result = llm.expand_query(q)
        elapsed = time.time() - t0
        has_keywords = len(result.keywords) > 0
        print_result(
            f"expand '{q[:30]}...'",
            has_keywords,
            f"keywords={result.keywords}, synonyms={result.synonyms}, "
            f"english={result.english_terms} ({elapsed:.1f}s)",
        )

    # 1b. Intent Decomposition
    print("\n  [Intent Decomposition]")
    multi_queries = [
        "Find a laptop under $1000, order it, and send confirmation email",
        "날씨 확인하고 이메일로 알려줘",
    ]
    for q in multi_queries:
        t0 = time.time()
        intents = llm.decompose_intents(q)
        elapsed = time.time() - t0
        has_intents = len(intents) > 0
        intent_strs = [f"{i.action}({i.target})" for i in intents]
        print_result(
            f"decompose '{q[:35]}...'",
            has_intents,
            f"intents={intent_strs} ({elapsed:.1f}s)",
        )


# ── TEST 2: OpenAI Function Calling ─────────────────────────────────


def test_function_calling():
    """직접 tool calling format으로 호출하여 도구 선택 능력 테스트."""
    print_header("TEST 2: OpenAI Function Calling Format")

    test_cases = [
        {
            "name": "단일 도구 - 날씨",
            "message": "What's the weather like in Seoul?",
            "expected_tool": "get_weather",
            "expected_args": ["city"],
        },
        {
            "name": "단일 도구 - 이메일",
            "message": "Send an email to john@example.com saying hello",
            "expected_tool": "send_email",
            "expected_args": ["to"],
        },
        {
            "name": "단일 도구 - 상품 검색",
            "message": "Find me laptops under $500",
            "expected_tool": "search_products",
            "expected_args": ["query"],
        },
        {
            "name": "단일 도구 - 주문 취소",
            "message": "Cancel order ORD-12345 because I changed my mind",
            "expected_tool": "cancel_order",
            "expected_args": ["order_id"],
        },
        {
            "name": "도구 불필요 - 일반 대화",
            "message": "Hello, how are you?",
            "expected_tool": None,
            "expected_args": [],
        },
    ]

    for tc in test_cases:
        t0 = time.time()
        try:
            result = chat(
                messages=[{"role": "user", "content": tc["message"]}],
                tools=TOOLS,
            )
            elapsed = time.time() - t0
            choice = result["choices"][0]
            msg = choice["message"]

            tool_calls = msg.get("tool_calls", [])
            finish_reason = choice.get("finish_reason", "")

            if tc["expected_tool"] is None:
                # 도구 호출하지 않아야 하는 케이스
                passed = len(tool_calls) == 0
                detail = f"finish={finish_reason}, tool_calls={len(tool_calls)}"
            else:
                if tool_calls:
                    called = tool_calls[0]
                    func_name = called.get("function", {}).get("name", "")
                    func_args_raw = called.get("function", {}).get("arguments", "{}")
                    try:
                        func_args = (
                            json.loads(func_args_raw)
                            if isinstance(func_args_raw, str)
                            else func_args_raw
                        )
                    except json.JSONDecodeError:
                        func_args = {}

                    name_match = func_name == tc["expected_tool"]
                    args_present = all(k in func_args for k in tc["expected_args"])
                    passed = name_match and args_present

                    detail = (
                        f"called={func_name}, args={json.dumps(func_args, ensure_ascii=False)}"
                        f" ({elapsed:.1f}s)"
                    )
                else:
                    passed = False
                    content_preview = msg.get("content", "")[:80]
                    detail = f"NO tool call, got text: '{content_preview}...' ({elapsed:.1f}s)"

        except Exception as e:
            passed = False
            detail = f"ERROR: {e}"
            elapsed = time.time() - t0

        print_result(tc["name"], passed, detail)


# ── TEST 3: graph-tool-call retrieve + LLM 조합 ─────────────────────


def test_retrieve_with_llm():
    """ToolGraph retrieve 후 LLM에게 도구 선택시키는 end-to-end 테스트."""
    print_header("TEST 3: ToolGraph Retrieve + LLM Tool Selection (E2E)")

    from graph_tool_call import ToolGraph

    tg = ToolGraph()
    tg.add_tools(TOOLS)

    # 관계 추가
    tg.add_relation("search_products", "create_order", "requires")
    tg.add_relation("create_order", "cancel_order", "complementary")
    tg.add_relation("get_weather", "send_email", "complementary")

    test_queries = [
        {
            "query": "I want to buy a laptop",
            "expected_retrieval": ["search_products", "create_order"],
            "expected_tool": "search_products",
        },
        {
            "query": "Cancel my order ORD-999",
            "expected_retrieval": ["cancel_order"],
            "expected_tool": "cancel_order",
        },
        {
            "query": "Check Seoul weather and email it to me",
            "expected_retrieval": ["get_weather", "send_email"],
            "expected_tool": "get_weather",  # 첫 번째로 호출할 도구
        },
    ]

    for tc in test_queries:
        # Step 1: graph-tool-call로 관련 도구 검색
        retrieved = tg.retrieve(tc["query"], top_k=3)
        retrieved_names = [t.name for t in retrieved]

        retrieval_hit = any(e in retrieved_names for e in tc["expected_retrieval"])
        print_result(
            f"retrieve '{tc['query'][:30]}...'",
            retrieval_hit,
            f"got={retrieved_names}",
        )

        # Step 2: 검색된 도구만 LLM에 전달
        filtered_tools = [t for t in TOOLS if t["function"]["name"] in retrieved_names]

        t0 = time.time()
        try:
            result = chat(
                messages=[{"role": "user", "content": tc["query"]}],
                tools=filtered_tools,
            )
            elapsed = time.time() - t0
            choice = result["choices"][0]
            tool_calls = choice["message"].get("tool_calls", [])

            if tool_calls:
                func_name = tool_calls[0].get("function", {}).get("name", "")
                func_args_raw = tool_calls[0].get("function", {}).get("arguments", "{}")
                try:
                    func_args = (
                        json.loads(func_args_raw)
                        if isinstance(func_args_raw, str)
                        else func_args_raw
                    )
                except json.JSONDecodeError:
                    func_args = {}
                passed = func_name == tc["expected_tool"]
                detail = f"LLM chose={func_name}, args={json.dumps(func_args, ensure_ascii=False)} ({elapsed:.1f}s)"
            else:
                passed = False
                content = choice["message"].get("content", "")[:80]
                detail = f"NO tool call: '{content}' ({elapsed:.1f}s)"
        except Exception as e:
            passed = False
            detail = f"ERROR: {e}"

        print_result(f"  LLM select '{tc['expected_tool']}'", passed, detail)


# ── MAIN ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("  Bonsai-8B (1-bit Q1_0) Tool Calling Benchmark")
    print("  Model: localhost:8080 | OpenAI-compatible API")
    print("#" * 60)

    results = {}

    # Test 1
    try:
        test_search_llm()
    except Exception as e:
        print(f"  [!] Test 1 failed: {e}")

    # Test 2
    try:
        test_function_calling()
    except Exception as e:
        print(f"  [!] Test 2 failed: {e}")

    # Test 3
    try:
        test_retrieve_with_llm()
    except Exception as e:
        print(f"  [!] Test 3 failed: {e}")

    print(f"\n{'=' * 60}")
    print("  Done!")
    print(f"{'=' * 60}\n")
