"""Token saving verification: all tools vs gateway 2 tools.

Measures actual token usage difference when binding all tools
vs only search_tools + call_tool gateway meta-tools.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
pytest = __import__("pytest")
ChatOllama = pytest.importorskip("langchain_ollama").ChatOllama

from graph_tool_call.langchain.gateway import create_gateway_tools


# --- Same 47 tools as e2e test ---

@tool
def create_user(username: str, email: str) -> str:
    """Create a new user account with username and email."""
    return json.dumps({"id": 1, "username": username, "email": email})

@tool
def get_user(user_id: int) -> str:
    """Get user profile by user ID."""
    return json.dumps({"id": user_id, "username": "john"})

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
    return json.dumps({"users": [{"id": 1}], "page": page})

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
    return json.dumps({"banned": True, "user_id": user_id})

@tool
def create_order(product_id: int, quantity: int) -> str:
    """Create a new order for a product."""
    return json.dumps({"order_id": 100, "product_id": product_id})

@tool
def get_order(order_id: int) -> str:
    """Get order details by order ID."""
    return json.dumps({"order_id": order_id, "status": "pending"})

@tool
def cancel_order(order_id: int) -> str:
    """Cancel an existing order."""
    return json.dumps({"order_id": order_id, "status": "cancelled"})

@tool
def list_orders(user_id: int) -> str:
    """List all orders for a user."""
    return json.dumps({"orders": [{"order_id": 100}]})

@tool
def update_order_status(order_id: int, status: str) -> str:
    """Update order status (pending, shipped, delivered)."""
    return json.dumps({"order_id": order_id, "status": status})

@tool
def process_refund(order_id: int) -> str:
    """Process a refund for a cancelled order."""
    return json.dumps({"order_id": order_id, "refunded": True})

@tool
def track_shipment(order_id: int) -> str:
    """Track shipment status for an order."""
    return json.dumps({"order_id": order_id, "tracking": "1Z999"})

@tool
def create_product(name: str, price: float) -> str:
    """Create a new product listing."""
    return json.dumps({"product_id": 1, "name": name, "price": price})

@tool
def get_product(product_id: int) -> str:
    """Get product details by product ID."""
    return json.dumps({"product_id": product_id, "name": "Widget"})

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
    return json.dumps({"products": [{"id": 1, "category": category}]})

@tool
def search_products(query: str) -> str:
    """Search products by name or description."""
    return json.dumps({"results": [{"id": 1, "name": query}]})

@tool
def charge_card(amount: float, card_token: str) -> str:
    """Charge a credit card."""
    return json.dumps({"charge_id": "ch_123", "amount": amount})

@tool
def get_payment(payment_id: str) -> str:
    """Get payment details."""
    return json.dumps({"payment_id": payment_id, "amount": 99.99})

@tool
def list_payments(user_id: int) -> str:
    """List payment history for a user."""
    return json.dumps({"payments": [{"id": "ch_123"}]})

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
    return json.dumps({"sent": True, "user_id": user_id})

@tool
def list_notifications(user_id: int) -> str:
    """List all notifications for a user."""
    return json.dumps({"notifications": [{"id": 1}]})

@tool
def upload_file(filename: str, content_type: str) -> str:
    """Upload a file to storage."""
    return json.dumps({"file_id": "f_123", "filename": filename})

@tool
def download_file(file_id: str) -> str:
    """Download a file from storage."""
    return json.dumps({"file_id": file_id, "url": "https://example.com/f"})

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
    return json.dumps({"total_users": 1000, "revenue": 150000})

@tool
def get_sales_report(start_date: str, end_date: str) -> str:
    """Generate sales report for a date range."""
    return json.dumps({"start": start_date, "end": end_date, "total": 50000})

@tool
def get_user_activity(user_id: int) -> str:
    """Get activity log for a user."""
    return json.dumps({"user_id": user_id, "actions": ["login"]})

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
    return json.dumps({"city": city, "days": days})

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
    return json.dumps({"theme": "dark", "language": "en"})

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


def _count_tool_schema_chars(tools: list) -> int:
    """Estimate tool schema size by serializing to OpenAI function format."""
    total = 0
    for t in tools:
        schema = {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
            }
        }
        if hasattr(t, "args_schema") and t.args_schema:
            try:
                schema["function"]["parameters"] = t.args_schema.model_json_schema()
            except Exception:
                pass
        total += len(json.dumps(schema))
    return total


def main():
    print("=" * 70)
    print("Token Saving Verification: All Tools vs Gateway")
    print("=" * 70)

    llm = ChatOllama(model="qwen3.5:4b", temperature=0)
    query = "What's the weather in Seoul?"

    # --- Method 1: All tools bound ---
    print(f"\n[1] All {len(ALL_TOOLS)} tools bound to LLM")
    llm_all = llm.bind_tools(ALL_TOOLS)
    # Measure schema chars
    all_chars = _count_tool_schema_chars(ALL_TOOLS)
    all_tokens_est = all_chars // 4
    print(f"    Tool schema size: {all_chars:,} chars (~{all_tokens_est:,} tokens)")

    # Actually invoke and check prompt_tokens
    result_all = llm_all.invoke(query)
    meta_all = result_all.response_metadata
    usage_all = meta_all.get("usage", meta_all.get("token_usage", {}))
    prompt_all = usage_all.get("prompt_tokens", usage_all.get("input_tokens", "N/A"))
    print(f"    Actual prompt_tokens: {prompt_all}")
    print(f"    Tool calls: {[tc['name'] for tc in (result_all.tool_calls or [])]}")

    # --- Method 2: Gateway 2 tools ---
    print(f"\n[2] Gateway 2 tools bound to LLM")
    gateway = create_gateway_tools(ALL_TOOLS, top_k=10)
    llm_gw = llm.bind_tools(gateway)
    gw_chars = _count_tool_schema_chars(gateway)
    gw_tokens_est = gw_chars // 4
    print(f"    Tool schema size: {gw_chars:,} chars (~{gw_tokens_est:,} tokens)")

    result_gw = llm_gw.invoke(query)
    meta_gw = result_gw.response_metadata
    usage_gw = meta_gw.get("usage", meta_gw.get("token_usage", {}))
    prompt_gw = usage_gw.get("prompt_tokens", usage_gw.get("input_tokens", "N/A"))
    print(f"    Actual prompt_tokens: {prompt_gw}")
    print(f"    Tool calls: {[tc['name'] for tc in (result_gw.tool_calls or [])]}")

    # --- Comparison ---
    print(f"\n{'=' * 70}")
    print("COMPARISON")
    print(f"  Tool schema: {all_chars:,} → {gw_chars:,} chars ({(1 - gw_chars/all_chars)*100:.0f}% reduction)")
    print(f"  Estimated tokens: ~{all_tokens_est:,} → ~{gw_tokens_est:,} ({(1 - gw_tokens_est/all_tokens_est)*100:.0f}% reduction)")

    if isinstance(prompt_all, int) and isinstance(prompt_gw, int):
        actual_reduction = (1 - prompt_gw / prompt_all) * 100
        print(f"  Actual prompt_tokens: {prompt_all:,} → {prompt_gw:,} ({actual_reduction:.0f}% reduction)")
        saved = prompt_all - prompt_gw
        print(f"  Tokens saved per turn: {saved:,}")
    else:
        print(f"  Actual prompt_tokens: {prompt_all} → {prompt_gw} (check model metadata)")

    print("=" * 70)


if __name__ == "__main__":
    main()
