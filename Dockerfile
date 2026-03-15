FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir graph-tool-call[mcp]

EXPOSE 8000

ENTRYPOINT ["graph-tool-call", "serve"]
