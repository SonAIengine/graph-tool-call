---
title: 생태계 호환성
description: 주요 agent framework와 cloud gateway에 맞는 연동 방식을 선택합니다.
---

# 생태계 호환성

graph-tool-call의 검색과 graph build는 provider-neutral합니다. Python host에서는
in-process adapter를, 언어와 cloud platform을 독립적으로 유지하려면 MCP를 사용합니다.

## 지원 표

| 환경 | 권장 표면 | 상태 | 검증 |
| --- | --- | --- | --- |
| Python application | `ToolGraph`, `GraphToolkit` | native | repository test |
| OpenAI Responses API | `patch_openai` | native | Responses 형태 client test |
| OpenAI Chat Completions | `patch_openai` | compatibility | repository test |
| Anthropic Messages | `patch_anthropic` | native | repository test |
| LangChain v1 | `create_tool_selection_middleware` | native | 실제 LangChain dependency test |
| 기존 LangGraph ReAct | `create_agent` | compatibility | repository test |
| OpenAI Agents SDK | remote 또는 stdio MCP server | protocol integration | MCP contract test 후 app smoke 필요 |
| PydanticAI | remote MCP server를 가리키는 `MCPToolset` | protocol integration | app smoke 필요 |
| Google ADK | remote MCP server를 가리키는 `McpToolset` | protocol integration | app smoke 필요 |
| AWS AgentCore Gateway | private remote MCP target | deployment recipe | AWS 계정에서 IAM/OAuth 검증 필요 |
| Microsoft Foundry Toolbox | private remote MCP endpoint | deployment recipe | tenant에서 Entra/connection 검증 필요 |
| JavaScript, Java, Go | MCP client | protocol integration | client별 smoke 필요 |

`protocol integration`은 graph-tool-call endpoint가 MCP를 따른다는 뜻입니다. 외부
framework의 connection lifecycle, approval, execution policy까지 이 repository가 모든
버전에서 검증한다는 의미는 아닙니다.

## 선택 기준

- 기존 SDK client가 실행을 담당하고 function catalog만 줄이면
  `patch_openai` 또는 `patch_anthropic`을 사용합니다.
- 권한, runtime context, 대화 단계에 따라 tool이 달라지면 LangChain v1 middleware를
  사용합니다.
- OpenAI Agents, PydanticAI, Google ADK, desktop client, non-Python runtime에는 MCP를
  사용합니다.
- managed identity, OAuth, private network, policy enforcement가 필요하면 MCP server
  앞에 AWS/Azure gateway를 둡니다.

## 알려진 경계

- product auth와 tenant policy는 host 또는 managed gateway가 담당합니다.
- MCP client마다 dynamic tool list caching 동작이 다를 수 있어 proxy는
  `call_backend_tool` fallback을 유지합니다.
- 직접 TypeScript/Java SDK는 아직 제공하지 않으며 해당 runtime은 MCP를 사용합니다.
- OpenAPI callback/webhook은 metadata-only이고 GraphQL subscription은 application
  transport adapter가 필요합니다.

## 관련 문서

- [배포](./deployment.md)
- [MCP Server](./mcp-server.md)
- [MCP Proxy](./mcp-proxy.md)
- [LangChain](./langchain.md)
- [Middleware](./middleware.md)
