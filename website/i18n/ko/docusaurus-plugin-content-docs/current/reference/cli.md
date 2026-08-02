---
title: CLI
description: tool graph를 ingest, inspect, search, serve, execute하는 command-line workflow입니다.
---

# CLI

패키지는 `graph-tool-call` 명령을 제공합니다. 로컬에서 tool catalog를
시험하거나, adapter가 저장할 collection artifact를 만들거나, readiness
check와 MCP server를 실행할 때 사용합니다.

```bash
graph-tool-call --version
graph-tool-call --help
```

## Command 개요

| Command | 용도 |
| --- | --- |
| `demo` | Offline target-plus-producer launch demo 실행 |
| `search` | build 없이 OpenAPI source나 graph file에서 one-shot 검색 |
| `ingest` | 재사용 가능한 `ToolGraph` JSON 생성 |
| `retrieve` | 이미 build된 graph 검색 |
| `inspect-openapi` | deterministic OpenAPI readiness 진단 |
| `build-openapi-collection` | 저장 가능한 collection artifact 생성 |
| `analyze` | graph 구조, duplicate, conflict, orphan 확인 |
| `visualize` | HTML, GraphML, Cypher export |
| `info` | node/edge summary 출력 |
| `dashboard` | local interactive dashboard 실행 |
| `call` | OpenAPI tool search 후 built-in HTTP executor로 호출 |
| `serve` | MCP server로 실행 |
| `proxy` | 여러 MCP backend를 aggregate/filter |

## Offline Demo 실행

고정된 ecommerce contract를 실제 retrieval, target selection,
dependency-closure pipeline으로 처리합니다. Network와 optional dependency가
필요하지 않습니다.

```bash
graph-tool-call demo dependency-chain
graph-tool-call demo dependency-chain --json
```

## Build 없이 검색

```bash
graph-tool-call search "find pets by status" \
  --source https://petstore3.swagger.io/api/v3/openapi.json \
  --top-k 8 \
  --scores
```

script나 fixture에서는 JSON output을 사용하세요.

```bash
graph-tool-call search "find pets by status" \
  --source ./openapi.json \
  --top-k 8 \
  --scores \
  --json
```

같은 source를 반복 검색할 때는 `--cache graph.json`을 사용합니다.

## Build 후 retrieve

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "cancel an order" --graph graph.json --top-k 8
graph-tool-call analyze graph.json --duplicates --orphans
```

주요 ingest flag:

| Flag | 용도 |
| --- | --- |
| `--required-only` | required parameter만 유지 |
| `--include-deprecated` | deprecated operation 포함 |
| `--embedding [MODEL]` | optional embedding index 생성 |
| `--organize` | automatic graph organization 실행 |
| `--llm PROVIDER/MODEL` | ontology enrichment에 LLM 사용 |
| `--allow-private-hosts` | 신뢰된 internal URL load 허용 |
| `--force` | cache가 있어도 rebuild |

## OpenAPI readiness inspect

```bash
graph-tool-call inspect-openapi ./openapi.json
graph-tool-call inspect-openapi ./openapi.json --json
```

제품별 field name은 엔진에 하드코딩하지 말고 옵션으로 넘깁니다.

```bash
graph-tool-call inspect-openapi ./openapi.json \
  --context-field mallNo,siteNo \
  --paging-field page,size \
  --search-filter-field keyword,searchType
```

## Collection artifact build

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  -o collection.json \
  --context-field mallNo,siteNo \
  --paging-field page,size \
  --auth-field Authorization,X-API-Key
```

alias 옵션은 `alias=canonical` 형태입니다.

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  --resource-alias goods=product,item=product \
  --action-alias 조회=read,등록=create \
  --module-alias memberMgmt=member
```

## Tool execute smoke

`call`은 local smoke test 용도입니다. 운영 adapter는 auth, tenancy, retry,
audit, mutation safety를 직접 통제하는 executor를 따로 두는 편이 좋습니다.

```bash
graph-tool-call call "find pet by id" \
  --source ./openapi.json \
  --base-url https://petstore3.swagger.io/api/v3 \
  --args '{"petId": 1}' \
  --dry-run
```

## MCP serve/proxy

```bash
graph-tool-call serve --graph graph.json --transport stdio
graph-tool-call proxy --config .mcp.json --top-k 10 --passthrough-threshold 30
```

## 관련 문서

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [MCP Server](../integrations/mcp-server.md)
- [MCP Proxy](../integrations/mcp-proxy.md)
