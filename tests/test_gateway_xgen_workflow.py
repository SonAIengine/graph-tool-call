"""E2E test: gateway tools with xgen-workflow realistic tool set.

xgen-workflow에서 실제 사용되는 MCP tool 구조를 시뮬레이션:
- Slack MCP (6 tools)
- GitHub MCP (8 tools)
- Atlassian MCP — Jira (19 tools) + Confluence (9 tools)
- MS365 MCP — Mail/Calendar/Teams (15 tools)
- API Tool Loader (5 tools)

총 62개 tool → gateway 2개로 변환 → LLM이 검색+실행.
"""
# ruff: noqa: E501 — mock JSON responses are intentionally one-line for readability

from __future__ import annotations

import json
import time

from langchain_core.tools import tool

pytest = __import__("pytest")
ChatOllama = pytest.importorskip("langchain_ollama").ChatOllama
from langgraph.prebuilt import create_react_agent  # noqa: E402

from graph_tool_call.langchain.gateway import create_gateway_tools  # noqa: E402

# ===================================================================
# Slack MCP Tools (6)
# ===================================================================


@tool
def slack_get_channel_id(channel_name: str) -> str:
    """Get the ID of a Slack channel by name."""
    return json.dumps({"channel_id": "C01234", "name": channel_name})


@tool
def slack_send_message(channel_id: str, message: str) -> str:
    """Send a message to a Slack channel."""
    return json.dumps({"ok": True, "channel": channel_id, "ts": "1234567890.123456"})


@tool
def slack_list_channels() -> str:
    """List all Slack channels in the workspace."""
    return json.dumps(
        {"channels": [{"id": "C01", "name": "general"}, {"id": "C02", "name": "dev"}]}
    )


@tool
def slack_list_users() -> str:
    """List all users in the Slack workspace."""
    return json.dumps({"users": [{"id": "U01", "name": "alice"}, {"id": "U02", "name": "bob"}]})


@tool
def slack_search_conversations(query: str) -> str:
    """Search Slack conversations by keyword."""
    return json.dumps({"messages": [{"text": f"Found: {query}", "channel": "C01"}]})


@tool
def slack_get_message_link(channel_id: str, message_ts: str) -> str:
    """Get a permalink to a specific Slack message."""
    return json.dumps({"permalink": f"https://slack.com/archives/{channel_id}/p{message_ts}"})


# ===================================================================
# GitHub MCP Tools (8)
# ===================================================================


@tool
def github_get_file(path: str, repo: str = "main-repo") -> str:
    """Get the contents of a file from a GitHub repository."""
    return json.dumps({"path": path, "content": "file content here", "sha": "abc123"})


@tool
def github_get_issues(repo: str, state: str = "open") -> str:
    """Get all issues from a GitHub repository."""
    return json.dumps({"issues": [{"number": 1, "title": "Bug fix", "state": state}]})


@tool
def github_search_issues(query: str) -> str:
    """Search issues across GitHub repositories."""
    return json.dumps({"items": [{"number": 42, "title": query, "state": "open"}]})


@tool
def github_create_issue(title: str, body: str, repo: str = "main-repo") -> str:
    """Create a new issue in a GitHub repository."""
    return json.dumps(
        {"number": 100, "title": title, "html_url": "https://github.com/repo/issues/100"}
    )


@tool
def github_create_pull_request(title: str, body: str, head: str, base: str = "main") -> str:
    """Create a new pull request in a GitHub repository."""
    return json.dumps({"number": 50, "title": title, "html_url": "https://github.com/repo/pull/50"})


@tool
def github_comment_on_issue(issue_number: int, comment: str) -> str:
    """Add a comment to a GitHub issue."""
    return json.dumps({"id": 999, "issue_number": issue_number, "body": comment})


@tool
def github_list_pull_requests(repo: str, state: str = "open") -> str:
    """List pull requests in a GitHub repository."""
    return json.dumps({"pull_requests": [{"number": 50, "title": "Feature PR", "state": state}]})


@tool
def github_get_pull_request(pull_number: int) -> str:
    """Get details of a specific pull request."""
    return json.dumps(
        {"number": pull_number, "title": "Feature", "mergeable": True, "additions": 50}
    )


# ===================================================================
# Atlassian — Jira Tools (19)
# ===================================================================


@tool
def jira_search_issues(jql: str, max_results: int = 50) -> str:
    """Search Jira issues using JQL query language."""
    return json.dumps(
        {"issues": [{"key": "PROJ-123", "summary": "Sample issue", "status": "Open"}], "total": 1}
    )


@tool
def jira_get_issue(issue_key: str) -> str:
    """Get details of a single Jira issue by key."""
    return json.dumps(
        {"key": issue_key, "summary": "Bug in login", "status": "In Progress", "assignee": "alice"}
    )


@tool
def jira_create_issue(project_key: str, summary: str, issue_type: str = "Task") -> str:
    """Create a new Jira issue or sub-task."""
    return json.dumps({"key": f"{project_key}-999", "summary": summary, "type": issue_type})


@tool
def jira_update_issue(issue_key: str, fields: str) -> str:
    """Update fields of a Jira issue."""
    return json.dumps({"key": issue_key, "updated": True})


@tool
def jira_get_transitions(issue_key: str) -> str:
    """Get available status transitions for a Jira issue."""
    return json.dumps(
        {"transitions": [{"id": "31", "name": "Done"}, {"id": "21", "name": "In Progress"}]}
    )


@tool
def jira_transition_issue(issue_key: str, transition_id: str) -> str:
    """Change the status of a Jira issue via transition."""
    return json.dumps({"key": issue_key, "transitioned": True, "transition_id": transition_id})


@tool
def jira_add_comment(issue_key: str, comment_body: str) -> str:
    """Add a comment to a Jira issue."""
    return json.dumps({"id": "10001", "issue_key": issue_key, "body": comment_body})


@tool
def jira_get_comments(issue_key: str) -> str:
    """Get all comments from a Jira issue."""
    return json.dumps({"comments": [{"id": "10001", "body": "Working on it", "author": "alice"}]})


@tool
def jira_list_projects() -> str:
    """List all Jira projects accessible to the user."""
    return json.dumps(
        {
            "projects": [
                {"key": "PROJ", "name": "Main Project"},
                {"key": "DEV", "name": "Development"},
            ]
        }
    )


@tool
def jira_get_project(project_key: str) -> str:
    """Get details of a specific Jira project."""
    return json.dumps({"key": project_key, "name": "Main Project", "lead": "alice"})


@tool
def jira_assign_issue(issue_key: str, assignee: str) -> str:
    """Assign a Jira issue to a user."""
    return json.dumps({"key": issue_key, "assignee": assignee})


@tool
def jira_add_worklog(issue_key: str, time_spent: str, comment: str = "") -> str:
    """Log time spent on a Jira issue."""
    return json.dumps({"issue_key": issue_key, "time_spent": time_spent, "logged": True})


@tool
def jira_search_users(query: str) -> str:
    """Search for Jira users by name or email."""
    return json.dumps({"users": [{"name": "alice", "email": "alice@example.com"}]})


@tool
def jira_delete_issue(issue_key: str) -> str:
    """Delete a Jira issue permanently."""
    return json.dumps({"key": issue_key, "deleted": True})


@tool
def jira_get_boards() -> str:
    """Get all Scrum/Kanban boards in Jira."""
    return json.dumps({"boards": [{"id": 1, "name": "Sprint Board", "type": "scrum"}]})


@tool
def jira_get_sprints(board_id: int) -> str:
    """Get sprints from a Jira board."""
    return json.dumps({"sprints": [{"id": 10, "name": "Sprint 5", "state": "active"}]})


@tool
def jira_link_issues(inward_key: str, outward_key: str, link_type: str = "Relates") -> str:
    """Link two Jira issues together."""
    return json.dumps({"linked": True, "inward": inward_key, "outward": outward_key})


@tool
def jira_get_attachments(issue_key: str) -> str:
    """Get attachments from a Jira issue."""
    return json.dumps({"attachments": [{"filename": "screenshot.png", "size": 102400}]})


@tool
def jira_add_attachment(issue_key: str, filename: str) -> str:
    """Add an attachment to a Jira issue."""
    return json.dumps({"issue_key": issue_key, "filename": filename, "uploaded": True})


# ===================================================================
# Atlassian — Confluence Tools (9)
# ===================================================================


@tool
def confluence_search(cql: str, limit: int = 25) -> str:
    """Search Confluence content using CQL query language."""
    return json.dumps(
        {"results": [{"id": "123", "title": "API Guide", "type": "page"}], "total": 1}
    )


@tool
def confluence_get_page(page_id: str) -> str:
    """Get a Confluence page by ID."""
    return json.dumps({"id": page_id, "title": "API Guide", "body": "Page content here..."})


@tool
def confluence_create_page(space_key: str, title: str, body: str) -> str:
    """Create a new Confluence page in a space."""
    return json.dumps({"id": "456", "title": title, "space": space_key})


@tool
def confluence_update_page(page_id: str, title: str, body: str) -> str:
    """Update an existing Confluence page."""
    return json.dumps({"id": page_id, "title": title, "updated": True})


@tool
def confluence_delete_page(page_id: str) -> str:
    """Delete a Confluence page."""
    return json.dumps({"id": page_id, "deleted": True})


@tool
def confluence_get_spaces(limit: int = 25) -> str:
    """List all Confluence spaces."""
    return json.dumps(
        {
            "spaces": [
                {"key": "DEV", "name": "Development"},
                {"key": "HR", "name": "Human Resources"},
            ]
        }
    )


@tool
def confluence_get_pages_in_space(space_key: str) -> str:
    """Get all pages in a Confluence space."""
    return json.dumps(
        {"pages": [{"id": "123", "title": "API Guide"}, {"id": "124", "title": "Setup Guide"}]}
    )


@tool
def confluence_add_comment(page_id: str, body: str) -> str:
    """Add a comment to a Confluence page."""
    return json.dumps({"id": "789", "page_id": page_id, "body": body})


@tool
def confluence_get_page_comments(page_id: str) -> str:
    """Get all comments from a Confluence page."""
    return json.dumps({"comments": [{"id": "789", "body": "Good doc!", "author": "bob"}]})


# ===================================================================
# MS365 MCP Tools (15)
# ===================================================================


@tool
def ms365_list_mails(folder: str = "inbox", top: int = 10) -> str:
    """List emails from Outlook mailbox."""
    return json.dumps(
        {"emails": [{"id": "m1", "subject": "Meeting tomorrow", "from": "boss@company.com"}]}
    )


@tool
def ms365_read_mail(message_id: str) -> str:
    """Read a specific email from Outlook."""
    return json.dumps(
        {
            "id": message_id,
            "subject": "Meeting",
            "body": "Please join at 3pm",
            "from": "boss@company.com",
        }
    )


@tool
def ms365_send_email(to: str, subject: str, body: str) -> str:
    """Send an email via Outlook."""
    return json.dumps({"sent": True, "to": to, "subject": subject})


@tool
def ms365_reply_to_email(message_id: str, body: str) -> str:
    """Reply to an email in Outlook."""
    return json.dumps({"replied": True, "message_id": message_id})


@tool
def ms365_list_calendar_events(start_date: str, end_date: str) -> str:
    """List calendar events within a date range."""
    return json.dumps(
        {"events": [{"subject": "Team standup", "start": start_date, "location": "Room A"}]}
    )


@tool
def ms365_create_event(subject: str, start: str, end: str, attendees: str = "") -> str:
    """Create a new calendar event in Outlook."""
    return json.dumps({"id": "e1", "subject": subject, "start": start, "end": end})


@tool
def ms365_delete_event(event_id: str) -> str:
    """Delete a calendar event."""
    return json.dumps({"deleted": True, "event_id": event_id})


@tool
def ms365_list_teams() -> str:
    """List all Microsoft Teams the user belongs to."""
    return json.dumps(
        {"teams": [{"id": "t1", "name": "Engineering"}, {"id": "t2", "name": "Design"}]}
    )


@tool
def ms365_list_team_channels(team_id: str) -> str:
    """List channels in a Microsoft Teams team."""
    return json.dumps(
        {"channels": [{"id": "ch1", "name": "General"}, {"id": "ch2", "name": "Dev"}]}
    )


@tool
def ms365_send_team_message(team_id: str, channel_id: str, message: str) -> str:
    """Send a message to a Microsoft Teams channel."""
    return json.dumps({"sent": True, "team_id": team_id, "channel_id": channel_id})


@tool
def ms365_list_files(folder_path: str = "/") -> str:
    """List files in OneDrive."""
    return json.dumps(
        {"files": [{"name": "report.xlsx", "size": 51200}, {"name": "notes.docx", "size": 10240}]}
    )


@tool
def ms365_create_task(title: str, due_date: str = "") -> str:
    """Create a task in Microsoft To Do / Planner."""
    return json.dumps({"id": "task1", "title": title, "due_date": due_date, "status": "notStarted"})


@tool
def ms365_list_tasks(plan_id: str = "default") -> str:
    """List tasks from Microsoft Planner."""
    return json.dumps({"tasks": [{"id": "task1", "title": "Review PR", "status": "inProgress"}]})


@tool
def ms365_list_contacts(top: int = 10) -> str:
    """List contacts from Outlook."""
    return json.dumps({"contacts": [{"name": "Alice Kim", "email": "alice@company.com"}]})


@tool
def ms365_get_contact(contact_id: str) -> str:
    """Get a specific contact from Outlook."""
    return json.dumps(
        {
            "id": contact_id,
            "name": "Alice Kim",
            "email": "alice@company.com",
            "phone": "+82-10-1234-5678",
        }
    )


# ===================================================================
# API Tool Loader Tools (5) — custom REST API tools
# ===================================================================


@tool
def api_get_product_inventory(product_code: str) -> str:
    """조회: 상품 코드로 재고 수량을 조회합니다. Query product inventory by product code."""
    return json.dumps({"product_code": product_code, "quantity": 150, "warehouse": "Seoul-01"})


@tool
def api_create_purchase_order(supplier_id: str, items: str) -> str:
    """생성: 공급업체에 발주서를 생성합니다. Create a purchase order to a supplier."""
    return json.dumps({"po_number": "PO-2024-001", "supplier_id": supplier_id, "status": "created"})


@tool
def api_get_customer_info(customer_id: str) -> str:
    """조회: 고객 ID로 고객 상세 정보를 조회합니다. Get customer details by customer ID."""
    return json.dumps(
        {"customer_id": customer_id, "name": "Kim Corp", "grade": "VIP", "credit_limit": 50000000}
    )


@tool
def api_submit_approval(document_id: str, action: str) -> str:
    """결재: 문서 결재를 승인 또는 반려합니다. Approve or reject a document in the approval workflow."""
    return json.dumps({"document_id": document_id, "action": action, "result": "processed"})


@tool
def api_get_sales_dashboard(period: str = "monthly") -> str:
    """대시보드: 매출 현황 대시보드 데이터를 조회합니다. Get sales dashboard data."""
    return json.dumps(
        {"period": period, "total_sales": 1250000000, "orders": 3400, "growth": "+12.5%"}
    )


# ===================================================================
# Collect all tools
# ===================================================================

ALL_TOOLS = [
    # Slack (6)
    slack_get_channel_id,
    slack_send_message,
    slack_list_channels,
    slack_list_users,
    slack_search_conversations,
    slack_get_message_link,
    # GitHub (8)
    github_get_file,
    github_get_issues,
    github_search_issues,
    github_create_issue,
    github_create_pull_request,
    github_comment_on_issue,
    github_list_pull_requests,
    github_get_pull_request,
    # Jira (19)
    jira_search_issues,
    jira_get_issue,
    jira_create_issue,
    jira_update_issue,
    jira_get_transitions,
    jira_transition_issue,
    jira_add_comment,
    jira_get_comments,
    jira_list_projects,
    jira_get_project,
    jira_assign_issue,
    jira_add_worklog,
    jira_search_users,
    jira_delete_issue,
    jira_get_boards,
    jira_get_sprints,
    jira_link_issues,
    jira_get_attachments,
    jira_add_attachment,
    # Confluence (9)
    confluence_search,
    confluence_get_page,
    confluence_create_page,
    confluence_update_page,
    confluence_delete_page,
    confluence_get_spaces,
    confluence_get_pages_in_space,
    confluence_add_comment,
    confluence_get_page_comments,
    # MS365 (15)
    ms365_list_mails,
    ms365_read_mail,
    ms365_send_email,
    ms365_reply_to_email,
    ms365_list_calendar_events,
    ms365_create_event,
    ms365_delete_event,
    ms365_list_teams,
    ms365_list_team_channels,
    ms365_send_team_message,
    ms365_list_files,
    ms365_create_task,
    ms365_list_tasks,
    ms365_list_contacts,
    ms365_get_contact,
    # API Tools (5)
    api_get_product_inventory,
    api_create_purchase_order,
    api_get_customer_info,
    api_submit_approval,
    api_get_sales_dashboard,
]


# ===================================================================
# Test cases — xgen-workflow 실제 사용 시나리오
# ===================================================================

TEST_CASES = [
    # Cross-service: Slack
    (
        "Slack #dev 채널에 배포 완료 메시지 보내줘",
        ["slack_send_message", "slack_get_channel_id"],
        "Slack 메시지 전송",
    ),
    # Cross-service: Jira
    (
        "XGEN-1234 이슈 상태를 Done으로 변경해줘",
        ["jira_transition_issue", "jira_get_transitions"],
        "Jira 이슈 상태 변경",
    ),
    # Cross-service: GitHub PR
    (
        "GitHub에 'fix: login bug' 제목으로 PR 만들어줘",
        ["github_create_pull_request"],
        "GitHub PR 생성",
    ),
    # Cross-service: Confluence
    (
        "Confluence DEV 스페이스에서 API 가이드 문서 찾아줘",
        ["confluence_search", "confluence_get_pages_in_space"],
        "Confluence 문서 검색",
    ),
    # Cross-service: MS365 mail
    (
        "오늘 받은 메일 목록 보여줘",
        ["ms365_list_mails"],
        "Outlook 메일 조회",
    ),
    # Cross-service: MS365 calendar
    (
        "내일 오후 2시에 팀 회의 일정 잡아줘",
        ["ms365_create_event"],
        "캘린더 일정 생성",
    ),
    # Cross-service: Teams
    (
        "Teams Engineering 채널에 메시지 보내줘",
        ["ms365_send_team_message", "ms365_list_teams"],
        "Teams 메시지 전송",
    ),
    # API tool: inventory
    (
        "상품코드 SKU-001의 재고 수량 확인해줘",
        ["api_get_product_inventory"],
        "재고 조회 API",
    ),
    # API tool: approval
    (
        "DOC-2024-100 문서 결재 승인해줘",
        ["api_submit_approval"],
        "결재 승인 API",
    ),
    # Cross-service: Jira + search
    (
        "이번 스프린트에 할당된 내 이슈 목록 보여줘",
        ["jira_search_issues", "jira_get_sprints"],
        "Jira 스프린트 이슈 조회",
    ),
]


def _count_tool_schema_chars(tools: list) -> int:
    total = 0
    for t in tools:
        schema = {"type": "function", "function": {"name": t.name, "description": t.description}}
        if hasattr(t, "args_schema") and t.args_schema:
            try:
                schema["function"]["parameters"] = t.args_schema.model_json_schema()
            except Exception:
                pass
        total += len(json.dumps(schema))
    return total


def main():
    print(f"{'=' * 70}")
    print("xgen-workflow Gateway E2E Test")
    print(f"{'=' * 70}")
    print("Tool breakdown:")
    print("  Slack MCP:      6 tools")
    print("  GitHub MCP:     8 tools")
    print("  Jira MCP:      19 tools")
    print("  Confluence MCP:  9 tools")
    print("  MS365 MCP:     15 tools")
    print("  API Loader:     5 tools")
    print(f"  Total:         {len(ALL_TOOLS)} tools → gateway 2 tools")
    print(f"{'=' * 70}")

    # Token savings
    all_chars = _count_tool_schema_chars(ALL_TOOLS)
    gateway = create_gateway_tools(ALL_TOOLS, top_k=10)
    gw_chars = _count_tool_schema_chars(gateway)
    reduction = (1 - gw_chars / all_chars) * 100
    print(f"\nToken savings: {all_chars:,} → {gw_chars:,} chars ({reduction:.0f}% reduction)")
    print(f"  ~{all_chars // 4:,} → ~{gw_chars // 4:,} tokens per turn")

    # LLM test
    llm = ChatOllama(model="qwen3.5:4b", temperature=0)
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

            tool_calls_log = []
            call_tool_targets = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_log.append(tc["name"])
                        if tc["name"] == "call_tool":
                            target = tc["args"].get("tool_name", "")
                            call_tool_targets.append(target)

            used_search = "search_tools" in tool_calls_log
            hit = any(e in call_tool_targets for e in expected_tools)
            status = "PASS" if hit else "FAIL"
            if hit:
                passed += 1

            print(f"  [{status}] search: {used_search} | targets: {call_tool_targets}")
            print(f"  expected: {expected_tools} | time: {elapsed:.1f}s")

            final_msg = messages[-1]
            if hasattr(final_msg, "content") and isinstance(final_msg.content, str):
                print(f"  answer: {final_msg.content[:120]}...")

        except Exception as e:
            elapsed = time.time() - start
            print(f"  [ERROR] {e} ({elapsed:.1f}s)")

    print(f"\n{'=' * 70}")
    print(f"RESULT: {passed}/{total} ({passed / total * 100:.0f}%)")
    print(f"  Tools: {len(ALL_TOOLS)} → 2 (gateway)")
    print(f"  Token reduction: {reduction:.0f}%")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
