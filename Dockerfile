FROM python:3.12-slim

WORKDIR /app

RUN groupadd --system graph-tool-call \
    && useradd --system --gid graph-tool-call --home-dir /app graph-tool-call

COPY pyproject.toml poetry.lock README.md LICENSE ./
COPY graph_tool_call ./graph_tool_call

RUN pip install --no-cache-dir ".[mcp,openapi]"

EXPOSE 8000

USER graph-tool-call

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

ENTRYPOINT ["graph-tool-call", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
