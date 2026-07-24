# 빠른 시작

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

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

## Tool Graph 빌드

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

## API Collection 점검

```bash
graph-tool-call inspect-openapi ./openapi.json --json
```

대형 OpenAPI collection을 agent에 연결하기 전에 실행하세요. 리포트는 schema
coverage, contract coverage, graph readiness, semantic quality, 안정적인 issue
code를 보여줍니다.

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

