# Ecosystem Compatibility

The engine is provider-neutral. Prefer in-process Python adapters when the host
is Python and MCP when the runtime, language, or cloud platform should remain
independent.

| Environment | Recommended integration | Status |
| --- | --- | --- |
| Python | `ToolGraph`, `GraphToolkit` | native and repository-tested |
| OpenAI Responses / Chat Completions | `patch_openai` | native and repository-tested |
| Anthropic Messages | `patch_anthropic` | native and repository-tested |
| LangChain v1 | `create_tool_selection_middleware` | native and repository-tested |
| Legacy LangGraph | `create_agent` | compatibility-tested |
| OpenAI Agents, PydanticAI, Google ADK | stdio or remote MCP server | protocol integration; app smoke required |
| AWS AgentCore, Microsoft Foundry | private remote MCP target | deployment recipe; account auth test required |
| JavaScript, Java, Go | MCP client | protocol integration |

Cloud identity, tenant policy, approvals, and credential injection stay in the
host platform or managed gateway. Direct TypeScript and Java SDKs are not
shipped yet.
