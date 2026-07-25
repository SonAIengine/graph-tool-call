---
title: MCP Proxy
description: 여러 MCP backend를 aggregate/filter해서 agent에 노출합니다.
---

# MCP Proxy

MCP proxy는 MCP client와 하나 이상의 backend MCP server 사이에 위치합니다.
backend tool 위에 searchable graph를 만들고, client에는 더 작고 필터링된 tool
surface를 노출합니다.

client가 너무 많은 tool을 보거나 여러 backend를 하나의 catalog처럼 검색해야
할 때 사용합니다.

## Proxy 실행

```bash
graph-tool-call proxy \
  --config .mcp.json \
  --top-k 10 \
  --passthrough-threshold 30
```

`--passthrough-threshold`는 작은 catalog를 단순하게 유지하기 위한 값입니다.
backend tool 수가 threshold보다 작으면 강한 filtering 없이 pass-through할 수
있습니다.

proxy는 두 가지 모드로 동작합니다.

| Mode | 조건 | Client가 보는 것 | 사용할 때 |
| --- | --- | --- | --- |
| gateway | catalog size가 `--passthrough-threshold`보다 큼 | `search_tools`, `get_tool_schema`, `call_backend_tool`, 이후 matched backend tool | 대형 또는 multi-server catalog |
| passthrough | catalog size가 threshold 이하 | backend tool 직접 노출 | filtering이 오히려 불편한 작은 catalog |

## HTTP transport

```bash
graph-tool-call proxy \
  --config proxy-config.json \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8000
```

## Config input

proxy는 일반 `.mcp.json` 스타일 파일이나 graph-tool-call proxy config를 읽을
수 있습니다.

```json
{
  "mcpServers": {
    "orders": {
      "command": "python",
      "args": ["orders_server.py"]
    }
  }
}
```

가능하면 backend credential은 runtime secret manager에 둡니다.

여러 backend가 같은 tool name을 노출하면 proxy는 backend 이름을 prefix로 붙여
충돌을 피합니다. 이렇게 하면 search 이후 direct tool call을 유지하면서 silent
collision을 막을 수 있습니다.

## Retrieval behavior

proxy는 graph-tool-call을 사용해 다음을 수행합니다.

- backend tool schema ingest
- description과 annotation normalize
- keyword와 optional embedding signal search
- compact candidate set 반환
- debugging을 위한 evidence 보존

## Gateway workflow

gateway mode에서는 client가 backend tool을 호출하기 전에 먼저 검색해야 합니다.

```text
tools/list
  -> search_tools({"query": "고객 환불을 생성해줘", "top_k": 8})
  -> tools/list refresh로 matched backend tool 노출
  -> get_tool_schema({"tool_name": "orders.create_refund"})
  -> matched backend tool 직접 호출
```

`call_backend_tool`은 dynamically injected tool을 직접 호출하지 못하는 client를
위한 fallback입니다. client가 지원한다면 direct call을 우선 사용합니다.

## Tuning

| Option | 효과 | 운영 기준 |
| --- | --- | --- |
| `--top-k` | `search_tools`가 기본 반환하는 tool 수 | client context window 안에 들어가게 작게 유지 |
| `--embedding` | optional embedding signal 활성화 | description 품질이 충분할 때 사용 |
| `--cache` | backend tool metadata와 retrieval state 저장 | backend startup이 느릴 때 사용 |
| `--passthrough-threshold` | passthrough/gateway mode 전환 | client가 많은 tool을 버거워하면 낮춤 |

## 사용하지 않는 편이 좋은 경우

- backend가 tool 몇 개만 노출하는 경우
- client가 raw backend capability discovery를 완전히 봐야 하는 경우
- product policy를 dedicated backend adapter 안에서 enforce해야 하는 경우
- tool catalog reduction보다 latency가 더 중요한 경우

## 실패 모드

| 증상 | 가능 원인 | 확인할 것 |
| --- | --- | --- |
| meta-tool만 보임 | gateway mode이고 아직 검색하지 않음 | `search_tools` 호출 후 `tools/list` refresh |
| direct backend tool이 없음 | matched tool injection 또는 client cache 문제 | `get_tool_schema`나 `call_backend_tool` fallback 사용 |
| 비슷한 이름이 여러 개 보임 | 여러 backend가 같은 tool name을 노출 | search result의 backend-prefixed name 확인 |
| ranking 품질이 낮음 | backend description이 얇거나 generic함 | annotation 추가 또는 richer metadata ingest |
| startup이 느림 | process start 때 모든 backend를 조회함 | `--cache` 활성화 또는 backend scope 축소 |

## 검증

```bash
poetry run pytest tests/test_mcp_proxy.py -q
```

수동 smoke test에서는 fixture backend로 proxy를 실행하고 gateway/passthrough mode를
확인한 뒤, 하나의 task를 검색해서 matched tool이 direct call 또는
`call_backend_tool`로 호출되는지 확인합니다.

## 관련 문서

- [MCP Server](./mcp-server.md)
- [MCP Ingestion](../build/mcp-ingestion.md)
- [Tool Graph 검색](../search/tool-graph-search.mdx)
