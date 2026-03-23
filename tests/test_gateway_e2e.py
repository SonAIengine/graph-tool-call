"""End-to-end test: gateway tools (search_tools + call_tool) with real LLM.

LLM이 search_tools → call_tool 흐름을 제대로 타는지 검증.
"""

from __future__ import annotations

import json
import time

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from graph_tool_call.langchain.gateway import create_gateway_tools


# ---------------------------------------------------------------------------
# 50 tools (same as test_create_agent_e2e.py)
# ---------------------------------------------------------------------------

@tool
def create_user(username: str, email: str) -> str:
    """Create a new user account with username and email."""
    return json.dumps({"id": 1, "username": username, "email": email})

@tool
def get_user(user_id: int) -> str:
    """Get user profile by user ID."""
    return json.dumps({"id": user_id, "username": "john", "email": "john@example.com"})

@tool
def update_user(user_id: int, email: str) -> str:
    """Update user profile information."""
    return json.dumps({"id": user_id, "email": email})

@tool
def delete_user(user_id: int) -> str:
    """Delete a user account permanently."""
    return json.dumps({"deleted": True, "id": user_id})

@tool
def list_users(page: int = 1) -> str:
    """List all users with pagination."""
    return json.dumps({"users": [{"id": 1, "username": "john"}], "page": page})

@tool
def search_users(query: str) -> str:
    """Search users by name or email."""
    return json.dumps({"results": [{"id": 1, "username": query}]})

@tool
def reset_password(user_id: int) -> str:
    """Send password reset email to user."""
    return json.dumps({"sent": True, "user_id": user_id})

@tool
def ban_user(user_id: int, reason: str) -> str:
    """Ban a user account with a reason."""
    return json.dumps({"banned": True, "user_id": user_id, "reason": reason})

@tool
def create_order(product_id: int, quantity: int) -> str:
    """Create a new order for a product."""
    return json.dumps({"order_id": 100, "product_id": product_id, "quantity": quantity})

@tool
def get_order(order_id: int) -> str:
    """Get order details by order ID."""
    return json.dumps({"order_id": order_id, "status": "pending", "total": 99.99})

@tool
def cancel_order(order_id: int) -> str:
    """Cancel an existing order."""
    return json.dumps({"order_id": order_id, "status": "cancelled"})

@tool
def list_orders(user_id: int) -> str:
    """List all orders for a user."""
    return json.dumps({"orders": [{"order_id": 100, "status": "pending"}]})

@tool
def update_order_status(order_id: int, status: str) -> str:
    """Update order status (pending, shipped, delivered)."""
    return json.dumps({"order_id": order_id, "status": status})

@tool
def process_refund(order_id: int) -> str:
    """Process a refund for a cancelled order."""
    return json.dumps({"order_id": order_id, "refunded": True, "amount": 99.99})

@tool
def track_shipment(order_id: int) -> str:
    """Track shipment status for an order."""
    return json.dumps({"order_id": order_id, "tracking": "1Z999AA10123456784"})

@tool
def create_product(name: str, price: float) -> str:
    """Create a new product listing."""
    return json.dumps({"product_id": 1, "name": name, "price": price})

@tool
def get_product(product_id: int) -> str:
    """Get product details by product ID."""
    return json.dumps({"product_id": product_id, "name": "Widget", "price": 29.99})

@tool
def update_product(product_id: int, price: float) -> str:
    """Update product price."""
    return json.dumps({"product_id": product_id, "price": price})

@tool
def delete_product(product_id: int) -> str:
    """Delete a product listing."""
    return json.dumps({"deleted": True, "product_id": product_id})

@tool
def list_products(category: str = "all") -> str:
    """List products by category."""
    return json.dumps({"products": [{"id": 1, "name": "Widget", "category": category}]})

@tool
def search_products(query: str) -> str:
    """Search products by name or description."""
    return json.dumps({"results": [{"id": 1, "name": query}]})

@tool
def charge_card(amount: float, card_token: str) -> str:
    """Charge a credit card."""
    return json.dumps({"charge_id": "ch_123", "amount": amount, "status": "succeeded"})

@tool
def get_payment(payment_id: str) -> str:
    """Get payment details."""
    return json.dumps({"payment_id": payment_id, "amount": 99.99, "status": "succeeded"})

@tool
def list_payments(user_id: int) -> str:
    """List payment history for a user."""
    return json.dumps({"payments": [{"id": "ch_123", "amount": 99.99}]})

@tool
def create_invoice(order_id: int) -> str:
    """Generate an invoice for an order."""
    return json.dumps({"invoice_id": "inv_123", "order_id": order_id})

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    return json.dumps({"sent": True, "to": to, "subject": subject})

@tool
def send_sms(phone: str, message: str) -> str:
    """Send an SMS text message."""
    return json.dumps({"sent": True, "phone": phone})

@tool
def send_push_notification(user_id: int, title: str, message: str) -> str:
    """Send a push notification to a user's device."""
    return json.dumps({"sent": True, "user_id": user_id, "title": title})

@tool
def list_notifications(user_id: int) -> str:
    """List all notifications for a user."""
    return json.dumps({"notifications": [{"id": 1, "title": "Order shipped"}]})

@tool
def upload_file(filename: str, content_type: str) -> str:
    """Upload a file to storage."""
    return json.dumps({"file_id": "f_123", "filename": filename})

@tool
def download_file(file_id: str) -> str:
    """Download a file from storage."""
    return json.dumps({"file_id": file_id, "url": "https://storage.example.com/f_123"})

@tool
def delete_file(file_id: str) -> str:
    """Delete a file from storage."""
    return json.dumps({"deleted": True, "file_id": file_id})

@tool
def list_files(folder: str = "/") -> str:
    """List files in a folder."""
    return json.dumps({"files": [{"id": "f_123", "name": "report.pdf"}]})

@tool
def get_dashboard_stats() -> str:
    """Get overview dashboard statistics."""
    return json.dumps({"total_users": 1000, "total_orders": 5000, "revenue": 150000})

@tool
def get_sales_report(start_date: str, end_date: str) -> str:
    """Generate sales report for a date range."""
    return json.dumps({"start": start_date, "end": end_date, "total": 50000})

@tool
def get_user_activity(user_id: int) -> str:
    """Get activity log for a user."""
    return json.dumps({"user_id": user_id, "actions": ["login", "view_product", "checkout"]})

@tool
def get_conversion_rate(period: str = "monthly") -> str:
    """Get conversion rate analytics."""
    return json.dumps({"period": period, "rate": 0.032})

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return json.dumps({"city": city, "temp": 22, "condition": "sunny"})

@tool
def get_forecast(city: str, days: int = 7) -> str:
    """Get weather forecast for next N days."""
    return json.dumps({"city": city, "days": days, "forecast": [{"day": 1, "temp": 22}]})

@tool
def create_event(title: str, date: str) -> str:
    """Create a calendar event."""
    return json.dumps({"event_id": "e_123", "title": title, "date": date})

@tool
def list_events(date: str) -> str:
    """List calendar events for a date."""
    return json.dumps({"events": [{"id": "e_123", "title": "Meeting"}]})

@tool
def delete_event(event_id: str) -> str:
    """Delete a calendar event."""
    return json.dumps({"deleted": True, "event_id": event_id})

@tool
def get_settings() -> str:
    """Get current application settings."""
    return json.dumps({"theme": "dark", "language": "en", "notifications": True})

@tool
def update_settings(key: str, value: str) -> str:
    """Update an application setting."""
    return json.dumps({"key": key, "value": value, "updated": True})

@tool
def translate_text(text: str, target_lang: str) -> str:
    """Translate text to a target language."""
    return json.dumps({"original": text, "translated": f"[{target_lang}] {text}"})

@tool
def generate_report(report_type: str) -> str:
    """Generate a system report (daily, weekly, monthly)."""
    return json.dumps({"type": report_type, "generated": True})

@tool
def health_check() -> str:
    """Check system health status."""
    return json.dumps({"status": "healthy", "uptime": "99.9%"})


ALL_TOOLS = [
    create_user, get_user, update_user, delete_user, list_users,
    search_users, reset_password, ban_user,
    create_order, get_order, cancel_order, list_orders,
    update_order_status, process_refund, track_shipment,
    create_product, get_product, update_product, delete_product,
    list_products, search_products,
    charge_card, get_payment, list_payments, create_invoice,
    send_email, send_sms, send_push_notification, list_notifications,
    upload_file, download_file, delete_file, list_files,
    get_dashboard_stats, get_sales_report, get_user_activity, get_conversion_rate,
    get_weather, get_forecast,
    create_event, list_events, delete_event,
    get_settings, update_settings,
    translate_text, generate_report, health_check,
]


# ---------------------------------------------------------------------------
# Test cases: (query, expected_tool_via_call_tool, label)
# ---------------------------------------------------------------------------

TEST_CASES = [
    (
        "What's the weather in Seoul?",
        ["get_weather"],
        "weather",
    ),
    (
        "Cancel order #500",
        ["cancel_order"],
        "cancel order",
    ),
    (
        "Send an email to alice@example.com with subject 'Hello' and body 'Hi'",
        ["send_email"],
        "send email",
    ),
    (
        "Create a new user with username 'bob' and email 'bob@test.com'",
        ["create_user"],
        "create user",
    ),
    (
        "Translate 'hello world' to Korean",
        ["translate_text"],
        "translate",
    ),
]


def main():
    print(f"Total tools: {len(ALL_TOOLS)}")
    print(f"Gateway tool 2개로 변환 → LLM이 search_tools + call_tool 사용")
    print("=" * 70)

    llm = ChatOllama(model="qwen3.5:4b", temperature=0)

    # Create gateway tools
    gateway = create_gateway_tools(ALL_TOOLS, top_k=10)
    print(f"Gateway tools: {[t.name for t in gateway]}")

    # Create agent with only 2 gateway tools
    agent = create_react_agent(model=llm, tools=gateway)

    passed = 0
    total = len(TEST_CASES)

    for query, expected_tools, label in TEST_CASES:
        print(f"\n--- [{label}] {query}")
        start = time.time()

        try:
            result = agent.invoke(
                {"messages": [("user", query)]},
                config={"recursion_limit": 25},
            )
            elapsed = time.time() - start

            messages = result["messages"]

            # Collect all tool calls
            tool_calls_log = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_log.append(tc["name"])

            # Check if call_tool was used with expected tool_name
            call_tool_targets = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if tc["name"] == "call_tool":
                            target = tc["args"].get("tool_name", "")
                            call_tool_targets.append(target)

            used_search = "search_tools" in tool_calls_log
            hit = any(e in call_tool_targets for e in expected_tools)
            status = "PASS" if hit else "FAIL"
            if hit:
                passed += 1

            print(f"  [{status}] search_tools 사용: {used_search}")
            print(f"  tool calls: {tool_calls_log}")
            print(f"  call_tool targets: {call_tool_targets}")
            print(f"  expected: {expected_tools}")
            print(f"  time: {elapsed:.1f}s")

            # Final answer
            final_msg = messages[-1]
            if hasattr(final_msg, "content") and isinstance(final_msg.content, str):
                print(f"  answer: {final_msg.content[:150]}...")

        except Exception as e:
            print(f"  [ERROR] {e}")

    print(f"\n{'=' * 70}")
    print(f"RESULT: {passed}/{total} ({passed/total*100:.0f}%)")
    print(f"  - LLM에 노출된 tool 수: 2 (search_tools, call_tool)")
    print(f"  - 실제 backend tool 수: {len(ALL_TOOLS)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
