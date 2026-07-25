---
title: Mental Model
description: Understand how graph-tool-call prepares a small, evidence-backed tool surface before an LLM acts.
---

# Mental Model

`graph-tool-call` is a retrieval and planning engine for large tool catalogs. It
does not replace the LLM. It prepares the tool surface so the LLM sees a smaller,
better ranked, and better explained set of choices.

## Pipeline

1. **Ingest** raw sources such as OpenAPI, MCP, or Python functions.
2. **Normalize** each operation into a stable `ToolSchema`.
3. **Analyze** request fields, response fields, auth requirements, semantic
   action, resource, and module signals.
4. **Build** graph edges from structure, contracts, manual evidence, and
   validated trace evidence.
5. **Retrieve** a compact candidate set for the current user query.
6. **Select** a final target with strong evidence guardrails around the LLM
   target.
7. **Plan** required producers, inputs, user slots, and execution order.
8. **Run** tools through the product adapter and stream structured events.
9. **Learn** from scrubbed success and failure traces after validation.

## Engine vs Adapter

The engine owns product-neutral logic:

- schema normalization
- semantic metadata
- IO contracts
- graph edges
- retrieval evidence
- target selection
- plan synthesis diagnostics
- learning suggestions

The adapter owns product-specific runtime concerns:

- database rows
- auth profiles
- user sessions
- HTTP execution
- SSE transport
- UI workflows
- collection storage

## Why Graphs

LLM tool catalogs often fail when the model receives too many loosely described
tools. The graph keeps relationships explicit: which tool produces a field,
which tool consumes it, which operations share a resource, and which paths have
been observed in successful runs.

The result is a catalog that can be searched, inspected, validated, and improved
without hiding the evidence in prompts.
