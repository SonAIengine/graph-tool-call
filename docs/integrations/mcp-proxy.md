# MCP Proxy

When you have many MCP servers, their tool names pile up in every LLM turn. **MCP Proxy** bundles them behind a single server: **172 tools → 3 meta-tools**, saving ~1,200 tokens per turn.

## How it works

```text
            ┌─────────────────────────────┐
Claude  ──▶ │  graph-tool-call MCP Proxy  │
            │  ┌───────────────────────┐  │     ┌──────────────┐
            │  │ search_tools          │  │ ──▶ │ playwright   │
            │  │ get_tool_schema       │  │ ──▶ │ filesystem   │
            │  │ call_backend_tool     │  │ ──▶ │ my-api       │
            │  └───────────────────────┘  │ ──▶ │ ...          │
            └─────────────────────────────┘     └──────────────┘
                  3 meta-tools                    N backends
```

The proxy starts each backend, indexes all tools into a `ToolGraph`, and exposes only 3 meta-tools to the LLM. After `search_tools`, matched tools are **dynamically injected** so the LLM can call them directly in 1 hop.

## Setup

### Step 1 — Create `backends.json`

```jsonc
// ~/backends.json
{
  "backends": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp", "--headless"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/home"]
    },
    "my-api": {
      "command": "uvx",
      "args": ["some-mcp-server"],
      "env": { "API_KEY": "sk-..." }
    }
  },
  "top_k": 10,
  "cache_path": "~/.cache/mcp-proxy-cache.json"
}
```

> **Embedding is optional.** Add `"embedding": "ollama/qwen3-embedding:0.6b"` for cross-language search (requires Ollama running). Without it, BM25 keyword search still works.

### Step 2 — Register the proxy with Claude Code

```bash
claude mcp add -s user tool-proxy -- \
  uvx "graph-tool-call[mcp]" proxy --config ~/backends.json
```

### Step 3 — Remove the original individual servers

```bash
claude mcp remove playwright -s user
claude mcp remove filesystem -s user
claude mcp remove my-api -s user
```

### Step 4 — Restart Claude Code and verify

```bash
claude mcp list
# tool-proxy: ... - ✓ Connected
# (individual servers should be gone)
```

## Remote transport

```bash
graph-tool-call proxy --config backends.json --transport sse --port 8000
```

## Passthrough mode (few tools)

When total tools across all backends is **≤ 30**, the proxy **skips the graph layer entirely** and exposes every backend tool directly. Zero overhead, no meta-tools, original tool names and schemas preserved.

This is useful when you want a **single MCP entry point** for several small servers without paying the search/meta-tool tax.

```bash
# Explicitly set the threshold (default: 30)
graph-tool-call proxy --config backends.json --passthrough-threshold 50
```

Or in `backends.json`:

```jsonc
{
  "backends": { ... },
  "passthrough_threshold": 50   // ≤ 50 → passthrough, > 50 → gateway
}
```

| Mode | When | Exposed tools |
|---|---|---|
| **gateway** (default) | total tools > threshold | `search_tools` + `get_tool_schema` + `call_backend_tool` |
| **passthrough** | total tools ≤ threshold | All backend tools directly (original names/schemas) |

## Alternative: `.mcp.json` config

```jsonc
// .mcp.json (project-level or global)
{
  "mcpServers": {
    "tool-proxy": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "proxy",
               "--config", "/path/to/backends.json"]
    }
  }
}
```
