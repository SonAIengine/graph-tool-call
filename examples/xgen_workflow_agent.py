"""xgen-workflow 실전 적용 예시: agent_core.py에 graph-tool-call 통합.

xgen-workflow의 AgentXgenNode → AgentPreparer → _create_agent_graph 흐름에서
graph-tool-call을 적용해 대규모 tool set을 동적 필터링하는 3가지 패턴.

사전 조건:
    pip install "graph-tool-call[langchain]==0.18.0"

핵심 포인트:
    - xgen-workflow는 langchain.agents.create_agent() 로 agent graph 생성
    - tool이 많아지면(50개+) 매 턴 전체 tool을 LLM에 넘기면 토큰 낭비 + 정확도 하락
    - graph-tool-call의 filter_tools / create_agent / create_gateway_tools로 해결

================================================================================
패턴 비교
================================================================================

| 패턴 | tool 규모 | 코드 변경량 | 특징 |
|------|-----------|-------------|------|
| A. filter_tools | 10~50개 | 2줄 추가 | prepare 단계에서 1회 필터링 |
| B. create_agent | 10~50개 | create_agent 교체 | 매 턴 자동 필터링 (query_mode 선택) |
| C. gateway | 50~500개 | create_gateway_tools 1줄 | 2개 meta-tool로 축약 |
"""

from __future__ import annotations

# =====================================================================
# 패턴 A: filter_tools — agent_core.py의 prepare 단계에서 적용
# =====================================================================
# 가장 간단한 적용 방법. 기존 코드에 2줄만 추가.
# AgentPreparer._prepare_llm_components() 에서 tools_list를 받은 후
# 사용자 쿼리 기반으로 필터링한다.
#
# 장점: 기존 create_agent (langchain) 그대로 사용, 변경 최소
# 단점: 첫 턴의 user message로만 필터링 (멀티턴 재필터 X)


def pattern_a_filter_tools():
    """
    xgen-workflow의 _prepare_llm_components 이후,
    _create_agent_graph 이전에 filter_tools를 끼워넣는 패턴.

    기존 코드 (agent_core.py:534-537):
        context.tools_list = tools_list
        if tools_list:
            tool_names = [getattr(t, 'name', str(t)) for t in tools_list]
            logger.info(f"[AGENT_TOOLS] 사용 가능한 도구 ({len(tools_list)}개): {tool_names}")

    변경 코드:
        from graph_tool_call import filter_tools
        context.tools_list = filter_tools(tools_list, context.processed_text, top_k=10)
    """
    from langchain_core.tools import tool

    # -- 시뮬레이션: xgen-workflow에 등록된 tool들 --
    @tool
    def search_products(query: str) -> str:
        """Search products in the e-commerce catalog."""
        return f"Found products matching: {query}"

    @tool
    def get_order_detail(order_id: str) -> str:
        """Get order details by order ID."""
        return f"Order {order_id}: shipped"

    @tool
    def cancel_order(order_id: str, reason: str) -> str:
        """Cancel an existing order."""
        return f"Order {order_id} cancelled: {reason}"

    @tool
    def create_refund(order_id: str, amount: float) -> str:
        """Create a refund for an order."""
        return f"Refund ${amount} for order {order_id}"

    @tool
    def send_notification(user_id: str, message: str) -> str:
        """Send push notification to a user."""
        return f"Notification sent to {user_id}"

    @tool
    def get_user_profile(user_id: str) -> str:
        """Get user profile information."""
        return f"Profile for {user_id}"

    @tool
    def update_inventory(product_id: str, quantity: int) -> str:
        """Update product inventory count."""
        return f"Inventory updated: {product_id} = {quantity}"

    @tool
    def generate_report(report_type: str, date_range: str) -> str:
        """Generate a business report."""
        return f"Report generated: {report_type}"

    @tool
    def upload_file(file_path: str, bucket: str) -> str:
        """Upload a file to cloud storage (MinIO/S3)."""
        return f"Uploaded {file_path} to {bucket}"

    @tool
    def query_database(sql: str) -> str:
        """Execute a SQL query on the analytics database."""
        return f"Query result: 42 rows"

    all_tools = [
        search_products, get_order_detail, cancel_order, create_refund,
        send_notification, get_user_profile, update_inventory,
        generate_report, upload_file, query_database,
    ]

    # -- 핵심: filter_tools 적용 (2줄) --
    from graph_tool_call import filter_tools

    user_query = "주문 123번 취소하고 환불 처리해줘"
    filtered = filter_tools(all_tools, user_query, top_k=5)

    print(f"  전체 tool: {len(all_tools)}개")
    print(f"  쿼리: '{user_query}'")
    print(f"  필터링 결과 ({len(filtered)}개): {[t.name for t in filtered]}")

    # -- agent_core.py 적용 시 실제 코드 --
    # (agent_core.py의 _prepare_llm_components 마지막에 추가)
    print("\n  [적용 위치] agent_core.py:519 이후")
    print("  ─" * 30)
    print("""
    # 기존 코드
    context.tools_list = tools_list

    # 추가 (2줄)
    from graph_tool_call import filter_tools
    context.tools_list = filter_tools(tools_list, context.processed_text, top_k=10)
    """)


# =====================================================================
# 패턴 B: create_agent — 매 턴 자동 필터링
# =====================================================================
# agent_core.py의 _create_agent_graph()에서 langchain.agents.create_agent를
# graph_tool_call.langchain.create_agent로 교체하는 패턴.
#
# 장점: 매 턴마다 쿼리 기반 재필터링 → 멀티턴 대화에 강함
# 장점: query_mode="llm" 으로 대명사 해소 가능 ("그거 취소해줘")
# 단점: import 교체 필요


def pattern_b_create_agent():
    """
    agent_core.py의 _create_agent_graph에서 create_agent 교체.

    기존 코드 (agent_core.py:761-767):
        from langchain.agents import create_agent

        context.agent_graph = create_agent(
            model=context.llm,
            tools=context.tools_list,
            system_prompt=context.system_prompt,
            middleware=[agent_summarization_middleware],
        )

    변경 코드:
        from graph_tool_call.langchain import create_agent as create_filtered_agent

        context.agent_graph = create_filtered_agent(
            model=context.llm,
            tools=context.tools_list,
            top_k=10,
            query_mode="llm",       # 멀티턴 대명사 해소
            query_model=small_llm,   # 쿼리 생성용 경량 모델 (비용 절감)
            system_prompt=context.system_prompt,
            middleware=[agent_summarization_middleware],
        )
    """
    from langchain_core.tools import tool

    # -- 시뮬레이션 --
    @tool
    def search_products(query: str) -> str:
        """Search products in the e-commerce catalog."""
        return f"Found: {query}"

    @tool
    def get_order_detail(order_id: str) -> str:
        """Get order details by order ID."""
        return f"Order {order_id}: shipped"

    @tool
    def cancel_order(order_id: str, reason: str) -> str:
        """Cancel an existing order."""
        return f"Cancelled: {order_id}"

    @tool
    def create_refund(order_id: str, amount: float) -> str:
        """Create a refund for an order."""
        return f"Refund: ${amount}"

    @tool
    def send_notification(user_id: str, message: str) -> str:
        """Send push notification to a user."""
        return f"Sent to {user_id}"

    all_tools = [search_products, get_order_detail, cancel_order,
                 create_refund, send_notification]

    # -- 핵심: create_agent 교체 --
    from graph_tool_call.langchain import create_agent as create_filtered_agent

    # query_mode="message": 기본값, 추가 LLM 호출 없음 (빠름)
    # query_mode="llm": 대화 컨텍스트에서 검색 쿼리 생성 (멀티턴 강함)
    print("  [query_mode 비교]")
    print("  ─" * 30)
    print('  "message" (기본): 마지막 user message를 그대로 검색 쿼리로 사용')
    print('  "llm":           대화 전체를 보고 LLM이 검색 쿼리 생성')
    print()

    # -- agent_core.py 적용 시 실제 코드 --
    print("  [적용 위치] agent_core.py:25 import + 750-773 _create_agent_graph()")
    print("  ─" * 30)
    print("""
    # import 변경 (agent_core.py:25)
    # 기존: from langchain.agents import create_agent
    # 변경:
    from langchain.agents import create_agent as _langchain_create_agent
    from graph_tool_call.langchain import create_agent as create_filtered_agent

    # _create_agent_graph 메서드 변경 (agent_core.py:750-773)
    def _create_agent_graph(self, context):
        agent_summarization_middleware = SummarizationMiddleware(
            model=context.llm,
            max_tokens_before_summary=25000,
            messages_to_keep=10,
        )

        TOOL_FILTER_THRESHOLD = 10  # tool 10개 이상이면 필터링 적용

        if context.tools_list and len(context.tools_list) >= TOOL_FILTER_THRESHOLD:
            # graph-tool-call: 매 턴 자동 필터링
            context.agent_graph = create_filtered_agent(
                model=context.llm,
                tools=context.tools_list,
                top_k=10,
                query_mode="llm",
                system_prompt=context.system_prompt,
                middleware=[agent_summarization_middleware],
            )
        elif context.tools_list:
            # tool 적으면 기존 방식
            context.agent_graph = _langchain_create_agent(
                model=context.llm,
                tools=context.tools_list,
                system_prompt=context.system_prompt,
                middleware=[agent_summarization_middleware],
            )
        else:
            context.agent_graph = _langchain_create_agent(
                model=context.llm,
                system_prompt=context.system_prompt,
                middleware=[agent_summarization_middleware],
            )
    """)


# =====================================================================
# 패턴 C: Gateway — 대규모 tool set을 2개 meta-tool로 축약
# =====================================================================
# MCP 서버, OpenAPI, 사용자 등록 tool이 50~500개일 때.
# search_tools + call_tool 2개로 축약해서 LLM 토큰을 극적으로 절감.
#
# xgen-workflow에서는 toolStorageController에서 가져온 tool들 +
# MCP 서버 tool들을 합쳐서 gateway로 넘기면 된다.


def pattern_c_gateway():
    """
    대규모 tool을 gateway 2개 tool로 축약.

    적용 위치: AgentXgenNode.execute() 에서 tools를 받은 직후,
    또는 tool 노드에서 agent에 전달하기 전.

    기존 흐름:
        tools (50~500개) → agent_core → LLM에 전체 tool schema 전달

    변경 흐름:
        tools (50~500개) → create_gateway_tools() → 2개 meta-tool → agent_core
    """
    import json
    from langchain_core.tools import tool

    # -- 시뮬레이션: DB에서 가져온 사용자 등록 tool 50개 --
    tools = []
    tool_categories = {
        "order": ["create_order", "get_order", "cancel_order", "update_order", "list_orders",
                  "get_order_status", "track_shipment", "confirm_delivery", "return_order",
                  "exchange_order"],
        "product": ["search_products", "get_product", "create_product", "update_product",
                    "delete_product", "get_product_reviews", "add_product_review",
                    "get_product_inventory", "update_price", "get_categories"],
        "user": ["get_user", "create_user", "update_user", "delete_user", "list_users",
                "get_user_orders", "get_user_wishlist", "add_to_wishlist",
                "get_user_notifications", "update_preferences"],
        "payment": ["process_payment", "create_refund", "get_payment_status",
                    "list_transactions", "get_invoice", "send_receipt",
                    "validate_coupon", "apply_discount", "get_billing_info",
                    "update_payment_method"],
        "admin": ["generate_report", "get_analytics", "export_data", "import_data",
                  "get_system_status", "clear_cache", "send_notification",
                  "create_announcement", "get_audit_log", "manage_permissions"],
    }

    for category, tool_names in tool_categories.items():
        for name in tool_names:
            # 동적 tool 생성 (실제로는 DB의 api_url, api_method 등으로 구성)
            from langchain_core.tools import StructuredTool

            t = StructuredTool.from_function(
                func=lambda input="", _n=name: json.dumps({"tool": _n, "status": "ok"}),
                name=name,
                description=f"{name.replace('_', ' ').title()} - {category} operation",
            )
            tools.append(t)

    print(f"  등록된 tool: {len(tools)}개")
    print(f"  카테고리: {list(tool_categories.keys())}")

    # -- 핵심: gateway 변환 (1줄) --
    from graph_tool_call.langchain import create_gateway_tools

    gateway = create_gateway_tools(tools, top_k=10)
    print(f"  → Gateway: {len(tools)}개 → {len(gateway)}개 meta-tool")
    print(f"  meta-tool: {[t.name for t in gateway]}")

    # -- agent_xgen.py 적용 시 실제 코드 --
    print("\n  [적용 위치] agent_xgen.py:1493 execute() 내부")
    print("  ─" * 30)
    print("""
    # agent_xgen.py execute() 메서드 내부, tools를 사용하기 전에 추가
    # (1493행 execute_agent 호출 전)

    # tool이 많으면 gateway로 축약
    GATEWAY_THRESHOLD = 30

    if tools and len(tools) >= GATEWAY_THRESHOLD:
        from graph_tool_call.langchain import create_gateway_tools
        tools = create_gateway_tools(tools, top_k=10)
        logger.info(f"[GATEWAY] {len(original_tools)}개 tool → {len(tools)}개 gateway tool로 축약")

    result = execute_agent(
        text=text,
        config=config,
        tools=tools,  # gateway tool 또는 원본 tool
        ...
    )
    """)


# =====================================================================
# 보너스: query_mode="llm" 멀티턴 시나리오
# =====================================================================
# xgen-workflow의 실제 사용 패턴:
# 사용자가 "아까 그 주문 취소해줘" 같이 맥락 의존적으로 말할 때
# query_mode="llm"이 대명사를 해소해서 올바른 tool을 찾는다.


def bonus_multiturn_scenario():
    """query_mode="llm" 이 빛나는 멀티턴 시나리오."""
    from graph_tool_call import ToolGraph
    from graph_tool_call.core.tool import ToolSchema

    # -- tool graph 구성 --
    tg = ToolGraph()
    tool_defs = [
        ("search_products", "Search products in the catalog by keyword"),
        ("get_order_detail", "Get order details and status by order ID"),
        ("cancel_order", "Cancel an existing order with reason"),
        ("create_refund", "Process a refund for a cancelled order"),
        ("send_notification", "Send push notification to user"),
        ("get_user_profile", "Get user profile information"),
        ("update_inventory", "Update product inventory count"),
        ("generate_report", "Generate business analytics report"),
    ]

    for name, desc in tool_defs:
        tg.add_tool(ToolSchema(name=name, description=desc))

    # -- 시뮬레이션: 멀티턴 대화 --
    scenarios = [
        {
            "turn": 1,
            "message": "주문번호 ORD-2024-456 상태 확인해줘",
            "expected": "get_order_detail",
        },
        {
            "turn": 2,
            "message": "그거 취소해줘",  # "그거" = 이전 턴의 주문
            "expected": "cancel_order",
            "note": "query_mode='message'면 '그거 취소해줘'로 검색 → 부정확",
        },
        {
            "turn": 3,
            "message": "환불도 해주고",  # 취소 후 자연스러운 후속 요청
            "expected": "create_refund",
        },
    ]

    print("  [멀티턴 시나리오]")
    print("  ─" * 30)

    for s in scenarios:
        results = tg.retrieve(s["message"], top_k=3)
        top_name = results[0].name if results else "없음"
        match = "✓" if top_name == s["expected"] else "✗"

        print(f"  턴 {s['turn']}: \"{s['message']}\"")
        print(f"    → message 모드 Top-1: {top_name} {match}")
        if "note" in s:
            print(f"    ※ {s['note']}")
        print()

    print("  query_mode='llm' 사용 시:")
    print("    턴 2의 '그거 취소해줘' → LLM이 'cancel order ORD-2024-456'으로 변환")
    print("    → cancel_order가 정확히 검색됨")


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("xgen-workflow + graph-tool-call 통합 가이드")
    print("=" * 70)

    print("\n━━━ 패턴 A: filter_tools (2줄 추가) ━━━")
    pattern_a_filter_tools()

    print("\n━━━ 패턴 B: create_agent 교체 (매 턴 자동 필터링) ━━━")
    pattern_b_create_agent()

    print("\n━━━ 패턴 C: Gateway (대규모 tool 축약) ━━━")
    pattern_c_gateway()

    print("\n━━━ 보너스: query_mode='llm' 멀티턴 시나리오 ━━━")
    bonus_multiturn_scenario()

    print("\n" + "=" * 70)
    print("적용 요약")
    print("=" * 70)
    print("""
    ┌─────────────┬────────────┬──────────────────────────────────┐
    │ tool 개수   │ 권장 패턴  │ 변경 사항                        │
    ├─────────────┼────────────┼──────────────────────────────────┤
    │ ~10개       │ 변경 불필요 │ 기존 create_agent 그대로         │
    │ 10~30개     │ 패턴 A/B   │ filter_tools 2줄 또는            │
    │             │            │ create_agent import 교체          │
    │ 30~500개    │ 패턴 C     │ create_gateway_tools 1줄 추가     │
    └─────────────┴────────────┴──────────────────────────────────┘

    pip install "graph-tool-call[langchain]==0.18.0"
    """)
