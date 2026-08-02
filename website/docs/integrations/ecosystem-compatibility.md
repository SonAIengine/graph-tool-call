---
title: Ecosystem Compatibility
description: Choose a supported integration path for popular agent frameworks and cloud gateways.
---

# Ecosystem Compatibility

graph-tool-call keeps search and graph construction provider-neutral. Use an
in-process adapter when the host is Python and MCP when the host runtime,
language, or cloud platform should remain independent.

## Support Matrix

| Environment | Recommended Surface | Status | Validation |
| --- | --- | --- | --- |
| Python applications | `ToolGraph`, `GraphToolkit` | native | repository tests |
| OpenAI Responses API | `patch_openai` | native | repository tests with Responses-shaped clients |
| OpenAI Chat Completions | `patch_openai` | compatibility | repository tests |
| Anthropic Messages | `patch_anthropic` | native | repository tests |
| LangChain v1 | `create_tool_selection_middleware` | native | real LangChain dependency test |
| Legacy LangGraph ReAct | `create_agent` | compatibility | repository tests |
| OpenAI Agents SDK | remote or stdio MCP server | protocol integration | MCP contract tests; run an app smoke test |
| PydanticAI | `MCPToolset` pointed at the remote MCP server | protocol integration | run an app smoke test |
| Google ADK | `McpToolset` pointed at the remote MCP server | protocol integration | run an app smoke test |
| AWS AgentCore Gateway | private remote MCP target | deployment recipe | validate IAM/OAuth in the owning AWS account |
| Microsoft Foundry Toolbox | private remote MCP endpoint | deployment recipe | validate Entra/project connection in the owning tenant |
| JavaScript, Java, Go | MCP client | protocol integration | client-specific smoke test required |

“Protocol integration” means the graph-tool-call endpoint follows MCP, while
the external framework remains responsible for connection lifecycle, approval,
and execution policy. It does not mean every provider version is tested in this
repository.

## Decision Guide

- Use `patch_openai` or `patch_anthropic` when an existing SDK client already
  owns execution and only the visible function catalog needs reduction.
- Use LangChain v1 middleware when tool availability changes with runtime
  context, permissions, or conversation state.
- Use MCP for OpenAI Agents, PydanticAI, Google ADK, desktop clients, and
  non-Python applications.
- Use an AWS/Azure gateway in front of the MCP service for managed identity,
  OAuth, private networking, and policy enforcement.

## Compatibility Policy

Core imports do not require framework packages. Optional integrations are lazy
and must fail with an installation command rather than breaking
`import graph_tool_call`. Release candidates run the core Python matrix and
focused integration tests. Cloud recipes require an account-owned smoke test
because credentials and network policy do not belong in this repository.

## Known Boundaries

- Product authentication and tenant policy stay in the host or managed gateway.
- MCP clients may differ in dynamic tool-list caching; the proxy also keeps
  `call_backend_tool` as a fallback.
- Direct TypeScript/Java SDKs are not shipped yet. Those runtimes use MCP.
- OpenAPI callbacks and webhooks are metadata-only; GraphQL subscriptions need
  an application transport adapter.

## Related Pages

- [Deployment](./deployment.md)
- [MCP Server](./mcp-server.md)
- [MCP Proxy](./mcp-proxy.md)
- [LangChain](./langchain.md)
- [Middleware](./middleware.md)
