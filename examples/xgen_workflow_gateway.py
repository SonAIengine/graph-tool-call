"""xgen-workflow 실전 적용 예시: MCP 서버 tool들을 gateway로 축약.

실제 MCP 서버(Slack, GitHub, Jira, MS365 등)에서 tool을 수집해
graph-tool-call gateway로 2개 meta-tool로 변환, agent가 동적으로
검색 → 실행하는 패턴을 보여준다.

사전 조건:
    pip install graph-tool-call[langchain] langchain-openai mcp

Usage:
    # 방법 1: MCP 서버에서 tool 자동 수집
    python examples/xgen_workflow_gateway.py --mcp

    # 방법 2: OpenAPI spec에서 tool 자동 생성
    python examples/xgen_workflow_gateway.py --openapi

    # 방법 3: 기존 LangChain tool list에 gateway 적용
    python examples/xgen_workflow_gateway.py --langchain
"""

from __future__ import annotations

import argparse
import asyncio
import json

# =====================================================================
# 방법 1: MCP 서버에서 tool 수집 → gateway
# =====================================================================
# 실제 MCP 서버(Slack, GitHub, Jira 등)에서 tool을 가져와서
# gateway 2개로 축약하는 패턴. xgen-workflow 실 적용 코드와 동일.


async def example_mcp_gateway():
    """MCP 서버에서 tool 수집 후 gateway agent 구성."""
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from graph_tool_call.langchain import create_gateway_tools

    # ── 1. MCP 서버에서 tool 수집 ────────────────────────────────
    # 실제 운영에서는 여러 MCP 서버를 순회하며 tool을 모은다.
    mcp_configs = {
        "github": StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
        ),
        "slack": StdioServerParameters(
            command="npx",
            args=["-y", "@anthropic/mcp-slack"],
            env={"SLACK_BOT_TOKEN": "xoxb-xxx"},
        ),
        # 필요한 만큼 추가
    }

    all_tools = []

    for server_name, params in mcp_configs.items():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                # MCP tool → LangChain StructuredTool 변환
                for t in response.tools:
                    from langchain_core.tools import StructuredTool

                    tool = StructuredTool.from_function(
                        func=lambda _s=session, _n=t.name, **kwargs: asyncio.run(
                            _s.call_tool(_n, kwargs)
                        ),
                        name=t.name,
                        description=t.description or "",
                    )
                    all_tools.append(tool)
        print(f"  [{server_name}] {len(response.tools)}개 tool 수집")

    # ── 2. Gateway 생성 (핵심 1줄) ───────────────────────────────
    gateway = create_gateway_tools(all_tools, top_k=10)
    print(f"\n  {len(all_tools)}개 tool → {len(gateway)}개 gateway tool")

    # ── 3. Agent 실행 ────────────────────────────────────────────
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_react_agent(model=llm, tools=gateway)

    result = agent.invoke(
        {"messages": [("user", "Slack #dev 채널에 배포 완료 메시지 보내줘")]},
        config={"recursion_limit": 15},
    )
    print(f"\n  Agent: {result['messages'][-1].content[:200]}")


# =====================================================================
# 방법 2: OpenAPI spec → graph-tool-call → gateway
# =====================================================================
# Swagger/OpenAPI에서 tool을 자동 생성하고 gateway에 넣는 패턴.
# 사내 API가 OpenAPI spec으로 문서화되어 있을 때 유용.


def example_openapi_gateway():
    """OpenAPI spec에서 tool 생성 후 gateway agent 구성."""
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    from graph_tool_call import ToolGraph
    from graph_tool_call.langchain import create_gateway_tools

    # ── 1. OpenAPI spec에서 ToolGraph 구축 ───────────────────────
    # URL 또는 파일 경로 모두 가능
    tg = ToolGraph.from_openapi(
        "https://petstore3.swagger.io/api/v3/openapi.json",
    )
    print(f"  OpenAPI에서 {len(tg.tools)}개 tool 생성")

    # 여러 spec 병합도 가능
    # tg.add_source("https://internal-api.company.com/v1/openapi.yaml")

    # ── 2. ToolGraph의 tool → LangChain tool로 변환 ──────────────
    from langchain_core.tools import StructuredTool

    langchain_tools = []
    for name, schema in tg.tools.items():
        # OpenAPI tool은 HTTP executor로 실제 호출 가능
        from graph_tool_call.execute.http_executor import build_request

        def make_fn(tool_schema=schema):
            def fn(**kwargs):
                req = build_request(tool_schema, kwargs)
                return json.dumps(
                    {
                        "method": req.method,
                        "url": req.url,
                        "body": req.body,
                        "note": "실제 환경에서는 requests.request()로 호출",
                    }
                )

            return fn

        tool = StructuredTool.from_function(
            func=make_fn(),
            name=name,
            description=schema.description or "",
        )
        langchain_tools.append(tool)

    # ── 3. Gateway 생성 ──────────────────────────────────────────
    gateway = create_gateway_tools(langchain_tools, top_k=5, graph=tg)
    print(f"  {len(langchain_tools)}개 tool → {len(gateway)}개 gateway tool")

    # ── 4. Agent 실행 ────────────────────────────────────────────
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_react_agent(model=llm, tools=gateway)

    result = agent.invoke(
        {"messages": [("user", "pet ID 42번 상세 정보 조회해줘")]},
        config={"recursion_limit": 15},
    )
    print(f"\n  Agent: {result['messages'][-1].content[:200]}")


# =====================================================================
# 방법 3: 기존 LangChain tool list에 gateway/filter 적용
# =====================================================================
# 이미 LangChain tool이 있는 프로젝트에서 gateway 또는 filter를
# 한 줄로 적용하는 패턴. 기존 코드 변경 최소화.


def example_langchain_integration():
    """기존 LangChain tool에 gateway/filter 적용."""
    from langchain_community.tools import DuckDuckGoSearchRun
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    # ── 기존 tool 정의 (프로젝트에 이미 있는 것들) ────────────────
    search = DuckDuckGoSearchRun()

    @tool
    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return json.dumps({"city": city, "temp": 22, "condition": "sunny"})

    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient."""
        return json.dumps({"sent": True, "to": to})

    @tool
    def create_calendar_event(title: str, date: str, time: str) -> str:
        """Create a calendar event."""
        return json.dumps({"created": True, "title": title})

    @tool
    def list_files(directory: str) -> str:
        """List files in a directory."""
        return json.dumps({"files": ["report.pdf", "data.csv"]})

    @tool
    def read_file(path: str) -> str:
        """Read a file from disk."""
        return json.dumps({"path": path, "content": "file content..."})

    @tool
    def query_database(sql: str) -> str:
        """Execute a SQL query on the database."""
        return json.dumps({"rows": [{"id": 1, "name": "test"}]})

    @tool
    def create_jira_issue(project: str, summary: str) -> str:
        """Create a new Jira issue."""
        return json.dumps({"key": f"{project}-100", "summary": summary})

    @tool
    def send_slack_message(channel: str, message: str) -> str:
        """Send a message to a Slack channel."""
        return json.dumps({"ok": True, "channel": channel})

    all_tools = [
        search,
        get_weather,
        send_email,
        create_calendar_event,
        list_files,
        read_file,
        query_database,
        create_jira_issue,
        send_slack_message,
    ]
    print(f"  기존 tool {len(all_tools)}개")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # ── 적용 방법 A: Gateway (tool 30개 이상일 때 권장) ───────────
    # 기존: agent = create_react_agent(model=llm, tools=all_tools)
    # 변경: tools에 create_gateway_tools() 감싸기만 하면 끝
    from graph_tool_call.langchain import create_gateway_tools

    gateway = create_gateway_tools(all_tools, top_k=5)
    agent_gw = create_react_agent(model=llm, tools=gateway)
    print(f"  → Gateway: {len(all_tools)}개 → {len(gateway)}개 tool")

    result = agent_gw.invoke(
        {"messages": [("user", "Slack #general에 '점검 완료' 보내줘")]},
        config={"recursion_limit": 15},
    )
    print(f"  Agent(gateway): {result['messages'][-1].content[:150]}")

    # ── 적용 방법 B: Auto-filter (tool 10~30개일 때 권장) ─────────
    # create_agent()가 매 턴마다 query 기반으로 tool을 자동 필터링.
    # LLM에는 top_k개만 노출되므로 token 절약 + 정확도 향상.
    from graph_tool_call.langchain import create_agent

    agent_af = create_agent(llm, tools=all_tools, top_k=3)
    print(f"  → Auto-filter: 매 턴 {len(all_tools)}개 중 3개만 노출")

    result = agent_af.invoke(
        {"messages": [("user", "오늘 날씨 어때?")]},
        config={"recursion_limit": 15},
    )
    print(f"  Agent(filter): {result['messages'][-1].content[:150]}")

    # ── 적용 방법 C: 수동 filter (완전한 제어) ────────────────────
    # 특정 시점에 직접 필터링해서 원하는 로직에 끼워 넣기.
    from graph_tool_call import filter_tools

    filtered = filter_tools(all_tools, "이메일 보내기", top_k=3)
    print(f"\n  수동 filter('이메일 보내기'): {[t.name for t in filtered]}")

    filtered = filter_tools(all_tools, "파일 읽고 DB 저장", top_k=3)
    print(f"  수동 filter('파일 읽고 DB 저장'): {[t.name for t in filtered]}")


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="xgen-workflow gateway 실전 예시")
    parser.add_argument("--mcp", action="store_true", help="MCP 서버 연동 예시")
    parser.add_argument("--openapi", action="store_true", help="OpenAPI spec 연동 예시")
    parser.add_argument("--langchain", action="store_true", help="기존 LangChain tool 연동 예시")
    args = parser.parse_args()

    # 아무 옵션도 없으면 전부 실행 안내
    if not any([args.mcp, args.openapi, args.langchain]):
        print("사용법:")
        print("  python examples/xgen_workflow_gateway.py --mcp       # MCP 서버 연동")
        print("  python examples/xgen_workflow_gateway.py --openapi   # OpenAPI spec 연동")
        print("  python examples/xgen_workflow_gateway.py --langchain # LangChain tool 연동")
        exit(0)

    if args.mcp:
        print("\n=== MCP 서버 → Gateway ===")
        asyncio.run(example_mcp_gateway())

    if args.openapi:
        print("\n=== OpenAPI → Gateway ===")
        example_openapi_gateway()

    if args.langchain:
        print("\n=== LangChain Tools → Gateway/Filter ===")
        example_langchain_integration()
