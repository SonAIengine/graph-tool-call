# CLI

패키지는 `graph-tool-call` 명령을 제공합니다.

## Search

```bash
graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

## Inspect OpenAPI

```bash
graph-tool-call inspect-openapi ./openapi.json
graph-tool-call inspect-openapi ./openapi.json --json
```

## 일반적인 흐름

```bash
graph-tool-call ingest ./openapi.json -o graph.json
graph-tool-call retrieve "cancel an order" --graph graph.json --top-k 8
graph-tool-call analyze graph.json
```

버전별 command 목록은 `graph-tool-call --help`로 확인하세요.

