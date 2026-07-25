---
title: 설치
description: OpenAPI, 한국어 검색, MCP, embedding, local development에 맞는 graph-tool-call extra 설치 방법입니다.
---

# 설치

코어 패키지는 작게 유지하고, 선택 기능은 extra로 제공합니다.

| Extra | 추가 기능 | 사용 시점 |
| --- | --- | --- |
| `openapi` | YAML parsing | YAML OpenAPI spec을 ingest할 때 |
| `korean` | Korean tokenizer | 한국어 질의와 영어 operationId가 섞인 API를 검색할 때 |
| `mcp` | MCP server/proxy | retrieval을 MCP로 노출할 때 |
| `embedding` | NumPy embedding hook | graph retrieval과 vector similarity를 함께 쓸 때 |
| `embedding-local` | sentence-transformers | 로컬 embedding model을 쓸 때 |
| `similarity` | fuzzy matching | duplicate detection이 필요할 때 |
| `visualization` | graph export dependency | graph 파일을 export할 때 |
| `dashboard` | Dash dashboard dependency | 로컬 interactive dashboard를 실행할 때 |

```bash
pip install graph-tool-call
pip install "graph-tool-call[openapi,korean]"
```

## Extra 선택

통합에 필요한 기능만 설치합니다.

```bash
# OpenAPI JSON/YAML ingestion
pip install "graph-tool-call[openapi]"

# 한국어 query와 영어 API catalog 혼합 검색
pip install "graph-tool-call[korean]"

# MCP server/proxy helper
pip install "graph-tool-call[mcp]"

# docs, examples, optional integration 전체
pip install "graph-tool-call[all]"
```

대형 OpenAPI API collection에서는 보통 다음 조합을 사용합니다.

```bash
pip install "graph-tool-call[openapi,korean]"
```

## 설치 확인

```bash
python - <<'PY'
import graph_tool_call
from graph_tool_call import ToolGraph

print(graph_tool_call.__version__)
print(ToolGraph)
PY
```

import가 되면 CLI도 확인합니다.

```bash
graph-tool-call --help
```

## 환경별 권장

| Environment | 권장 |
| --- | --- |
| application server | exact package version pin |
| local engine development | Poetry와 all extras |
| product adapter development | local editable install은 가능하지만 commit dependency에는 넣지 않음 |
| CI docs build | `website/` 아래 website dependency를 별도 설치 |

production adapter에서는 exact pin을 사용합니다.

```text
graph-tool-call[korean]==0.32.1
```

제품에서 검증한 version을 사용하세요. deployment manifest에서 latest로 floating하지 않습니다.

개발 환경:

```bash
poetry install --with dev --all-extras
poetry run pytest tests/ -q
```

## Troubleshooting

| 증상 | 가능 원인 | 해결 |
| --- | --- | --- |
| YAML OpenAPI 실패 | `openapi` extra 없음 | `graph-tool-call[openapi]` 설치 |
| 한국어 query 품질 낮음 | tokenizer extra 없음 | `graph-tool-call[korean]` 설치 |
| MCP server import 실패 | MCP SDK extra 없음 | `graph-tool-call[mcp]` 설치 |
| local embedding 사용 불가 | embedding extra 없음 | `embedding` 또는 `embedding-local` 설치 |
| 배포 후 동작이 갑자기 바뀜 | floating dependency | exact version pin 사용 |

## 다음 단계

[빠른 시작](./quickstart.md)에서 OpenAPI spec을 ingest하고 첫 retrieval query를 실행합니다.
