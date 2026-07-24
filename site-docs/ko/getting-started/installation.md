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

개발 환경:

```bash
poetry install --with dev --all-extras
poetry run pytest tests/ -q
```

