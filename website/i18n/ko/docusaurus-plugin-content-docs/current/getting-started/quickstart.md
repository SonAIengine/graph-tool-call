---
title: 빠른 시작
description: graph-tool-call을 설치하고 OpenAPI 검색, readiness 점검, 간단한 실행까지 확인합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# 빠른 시작

이 quickstart는 가장 작은 유용한 loop를 보여줍니다.

1. package 설치
2. OpenAPI spec 검색
3. Python에서 graph build
4. collection readiness 점검
5. 안전한 경우 간단한 operation 실행

## 설치

```bash
pip install graph-tool-call
```

필요한 extra만 골라 설치할 수 있습니다.

```bash
pip install "graph-tool-call[openapi]"
pip install "graph-tool-call[korean]"
pip install "graph-tool-call[mcp]"
pip install "graph-tool-call[all]"
```

## OpenAPI Spec 검색

빠른 smoke test에는 CLI를 사용하고, application이나 test suite에 연결할 때는
Python API를 사용합니다.

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json \
  --top-k 5 \
  --scores
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
results = graph.retrieve_with_scores("user authentication", top_k=5)

for result in results:
    print(result.tool.name, result.score, result.confidence)
```

  </TabItem>
  <TabItem value="evidence" label="Evidence">

```python
from graph_tool_call import ToolGraph
from graph_tool_call.graphify import retrieve_graphify

graph = ToolGraph.from_url("https://petstore3.swagger.io/api/v3/openapi.json")
response = retrieve_graphify(
    graph,
    "user authentication",
    top_k=5,
    include_evidence=True,
)

first = response["results"][0]
print(first["tool_name"])
print(first["score_breakdown"])
```

  </TabItem>
</Tabs>

CLI는 source를 로드하고 임시 graph를 만든 뒤 candidate를 검색해 가장 강한 match를
출력합니다. 코드를 작성하기 전에 spec을 빠르게 점검할 때 사용합니다.

## Tool Graph 빌드

반복 검색에서 매번 source를 ingest하지 않으려면 reusable graph를 만듭니다.

<Tabs>
  <TabItem value="python-cache" label="Python cache" default>

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.graph.json",
)

results = graph.retrieve("create a new pet", top_k=5)
for tool in results:
    print(tool.name)
```

  </TabItem>
  <TabItem value="cli-ingest" label="CLI graph">

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "create a new pet" --graph graph.json --top-k 5
```

  </TabItem>
  <TabItem value="collection" label="Collection artifact">

```bash
graph-tool-call build-openapi-collection ./openapi.json \
  -o collection.json \
  --context-field siteNo \
  --paging-field page,size
```

  </TabItem>
</Tabs>

local agent 실험에는 saved graph를 사용합니다. product adapter나 UI가 readiness,
semantic, edge-quality metadata를 저장해야 한다면 collection artifact를 사용합니다.

## API Collection 점검

```bash
graph-tool-call inspect-openapi ./openapi.json --json
```

대형 OpenAPI collection을 agent에 연결하기 전에 실행하세요. 리포트는 schema
coverage, contract coverage, graph readiness, semantic quality, 안정적인 issue
code를 보여줍니다.

주로 확인할 field는 다음입니다.

| Field | 중요한 이유 |
| --- | --- |
| `readiness_score` | collection readiness 요약 |
| `status` | `ready`, `warning`, `blocked` |
| `issues[].code` | repair를 위한 안정 reason code |
| `semantic_summary` | action/resource/module coverage |
| `edge_quality_summary` | graph edge evidence 품질 |

## Plan과 실행

```python
result = graph.execute(
    "addPet",
    {"name": "Buddy", "status": "available"},
    base_url="https://petstore3.swagger.io/api/v3",
)
```

실행 metadata는 OpenAPI contract에서 파생됩니다. path/query/header/body 위치,
content type, security requirement, response shape를 사용합니다.

auth readiness, required input, cleanup policy가 adapter에서 설정되기 전에는
production-like 환경에서 mutating API를 실행하지 않습니다.

## 다음 단계

- engine pipeline 이해: [Mental Model](./mental-model.md)
- 대형 spec build: [OpenAPI Ingestion](../build/openapi-ingestion.md)
- ranking evidence 확인: [Retrieval Signals](../search/retrieval-signals.md)
- collection 검증: [Quality Gates](../guides/quality-gates.md)
