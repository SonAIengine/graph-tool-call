---
title: MCP Server
description: graph-tool-call retrieval 기능을 MCP server로 노출합니다.
---

# MCP Server

MCP server는 graph-tool-call 기능을 Model Context Protocol로 노출합니다.
MCP-compatible client가 모든 backend tool을 한꺼번에 보는 대신, 작은 gateway
tool surface를 통해 대형 catalog를 검색하게 만들 때 사용합니다.

## Source에서 시작

```bash
graph-tool-call serve \
  --source ./openapi.json \
  --transport stdio
```

여러 source를 합칠 수도 있습니다.

```bash
graph-tool-call serve \
  --source ./orders.openapi.json \
  --source ./members.openapi.json
```

## 저장된 graph에서 시작

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call serve --graph graph.json --transport stdio
```

저장된 graph를 쓰면 process start 때마다 rebuild하지 않아도 됩니다.

## Client 설정

대부분의 MCP client는 local command로 server를 시작할 수 있습니다. 큰 OpenAPI
collection은 미리 graph를 만들어 두면 client가 ingest를 기다리지 않아도 됩니다.

```json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve", "--graph", "graph.json"]
    }
  }
}
```

개발 중에는 `--source`, 반복 가능한 환경에서는 `--graph`를 권장합니다. spec이
internal URL에 있으면 network policy와 함께 사용하고, `--allow-private-hosts`는
신뢰된 인프라에서만 켭니다.

## HTTP transport

```bash
graph-tool-call serve \
  --graph graph.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

기본은 private interface에 bind하는 것이 안전합니다. 외부 노출은 별도 network
및 auth control 뒤에 두세요.

| Transport | 사용할 때 | 메모 |
| --- | --- | --- |
| `stdio` | desktop/agent client가 process를 직접 시작할 때 | 가장 단순한 local setup |
| `sse` | client가 server-sent events를 기대할 때 | 기존 MCP 배포에 유용 |
| `streamable-http` | remote client가 HTTP로 연결할 때 | private bind 후 별도 auth layer를 붙이세요 |

## Tool surface

server는 작은 gateway surface만 노출합니다. LLM은 먼저 검색하고, 선택한 schema를
확인한 뒤, 해당 환경에서 안전한 execution adapter로 넘기는 흐름이 좋습니다.

| MCP tool | 목적 | 다음 단계 |
| --- | --- | --- |
| `search_tools` | 자연어 query에 맞는 tool 후보를 compact하게 반환 | best target의 `get_tool_schema` 호출 |
| `get_tool_schema` | parameter, method, path, category, tag 확인 | argument 준비 또는 product runner로 위임 |
| `list_categories` | category별 tool 수 확인 | domain을 좁히거나 query 개선 |
| `graph_info` | graph 크기, node/edge type, source metadata 확인 | build 품질 진단 |
| `execute_tool` | 내장 HTTP executor로 OpenAPI tool 실행 | demo 또는 통제된 내부 tooling에서 사용 |
| `load_source` | runtime에 OpenAPI source 추가 | 작은 catalog를 restart 없이 refresh |

## 권장 workflow

```text
search_tools("환불 가능한 주문을 찾아줘", top_k=5)
  -> get_tool_schema("getRefundableOrders")
  -> application adapter에서 실행
```

운영 시스템에서는 인증, tenant policy, audit logging, side-effect control을
product adapter에 둬야 합니다. `execute_tool`은 local test에는 유용하지만,
product-specific auth rule이 들어가는 위치가 되면 안 됩니다.

## Server가 책임질 것

- source 또는 graph load
- tool search
- compact candidate list 반환
- graph-tool-call capability를 MCP tool로 노출

책임지지 말아야 할 것:

- 운영 사용자 인증
- tenant-specific policy
- downstream API secret 원문
- product DB write

## 운영 메모

- 예측 가능한 startup을 위해 pre-built graph를 사용합니다.
- `--allow-private-hosts`는 신뢰된 인프라로 제한합니다.
- client나 wrapper에서 `top_k` limit을 작게 유지해 tool context를 줄입니다.
- query, selected tool, evidence는 남기되 secret 값은 남기지 않습니다.

## 실패 모드

| 증상 | 가능 원인 | 확인할 것 |
| --- | --- | --- |
| `No tools loaded` | 유효한 source/graph 없이 server가 시작됨 | 먼저 `graph-tool-call ingest SOURCE -o graph.json` 실행 |
| 후보가 너무 넓음 | tool description 또는 semantic metadata가 약함 | `graph_info` 확인 후 artifact rebuild |
| schema에 parameter가 없음 | OpenAPI request schema가 없거나 generic임 | OpenAPI readiness report 실행 |
| private URL load 실패 | URL safety policy가 internal host를 막음 | saved graph 사용 또는 trusted host만 허용 |
| API 실행 실패 | auth/base URL은 product adapter 책임임 | MCP server 밖의 runner/auth readiness 확인 |

## 검증

```bash
poetry run pytest tests/test_mcp_server.py -q
```

실제 client smoke test에서는 saved graph로 server를 띄우고, `search_tools`와
`get_tool_schema`가 기대한 parameter를 반환하는지 확인합니다. transcript에는
secret 원문이 남지 않아야 합니다.

## 관련 문서

- [MCP Ingestion](../build/mcp-ingestion.md)
- [MCP Proxy](./mcp-proxy.md)
- [CLI](../reference/cli.md)
