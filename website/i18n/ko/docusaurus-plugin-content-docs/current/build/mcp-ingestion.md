---
title: MCP Ingestion
description: MCP tool definition을 같은 graph engine에서 검색하고 plan할 수 있게 정규화합니다.
---

# MCP Ingestion

MCP ingestion은 model-context-protocol tool definition을 OpenAPI, Python tool과
같은 `ToolSchema` 표면으로 매핑합니다.

## Catalog 안에서의 역할

MCP tool은 enterprise OpenAPI보다 runtime description이 나은 경우가 많지만,
그래도 graph retrieval의 이점을 얻습니다.

- consistent annotation
- category와 relation analysis
- candidate filtering
- LLM용 compact tool list
- shared validation gate

## Tool List Ingest

adapter가 이미 MCP `tools/list` response를 가지고 있다면 `ingest_mcp_tools()`를
사용합니다.

```python
from graph_tool_call.ingest.mcp import ingest_mcp_tools

schemas = ingest_mcp_tools(
    [
        {
            "name": "read_file",
            "description": "Read a file",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
            "annotations": {"readOnlyHint": True},
        }
    ],
    server_name="filesystem",
)
```

parser는 `readOnlyHint`, `destructiveHint` 같은 MCP annotation과 parameter enum 값을
보존합니다.

## Graph에 Ingest

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_mcp_tools(mcp_tools, server_name="filesystem")

for tool in graph.retrieve("read a configuration file", top_k=3):
    print(tool.name)
```

`ToolGraph.ingest_mcp_tools()`는 schema를 등록하고, 다른 source와 같은 graph relation
logic으로 dependency detection을 실행할 수 있습니다.

## MCP Endpoint에서 Fetch

HTTP JSON-RPC MCP endpoint가 `tools/list`를 지원하면 직접 fetch할 수 있습니다.

```python
from graph_tool_call import ToolGraph

graph = ToolGraph()
graph.ingest_mcp_server(
    "https://mcp.example.com/mcp",
    timeout=30,
    max_response_bytes=5_000_000,
)
```

private host는 기본적으로 차단됩니다. 신뢰할 수 있는 infrastructure에서만 명시적으로
허용합니다.

```python
graph.ingest_mcp_server(
    "http://127.0.0.1:3000/mcp",
    allow_private_hosts=True,
)
```

## Normalized Metadata

| Field | 목적 |
| --- | --- |
| `metadata.source` | `mcp`로 설정 |
| `metadata.mcp_server` | argument, serverInfo, hostname에서 온 server name |
| `tags` | 가능한 경우 server name 포함 |
| `annotations` | MCP safety/behavior hint |
| `parameters` | normalized input schema property |

## Adapter Boundary

MCP server credential이나 runtime transport state는 graph engine이 소유하지
않습니다. 연결 정보는 MCP proxy에 두고, graph에는 정규화된 schema를 전달합니다.

## Failure Mode

| 증상 | 가능 원인 | 보완 |
| --- | --- | --- |
| invalid JSON | server가 JSON-RPC response를 반환하지 않음 | endpoint와 transport 확인 |
| tool 미검출 | response에 `result.tools` 또는 `tools`가 없음 | MCP server `tools/list` output 점검 |
| private host blocked | endpoint가 local/internal | trusted infrastructure에서만 opt-in |
| destructive tool이 높게 rank됨 | annotation 또는 query intent가 약함 | `destructiveHint` 보존과 validation case 추가 |

## 검증

```bash
poetry run pytest tests/test_ingest_mcp.py tests/test_mcp_annotations.py -q
```

## 관련 문서

- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
- [Tool Graph Search](/docs/search/tool-graph-search/)
