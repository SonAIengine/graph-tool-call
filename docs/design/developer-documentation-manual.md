# Developer Documentation Manual Design

## Goal

Move the public site from a polished project landing page to a durable developer
manual. The target quality bar is closer to Qdrant's product documentation than
to a marketing homepage:

- clear left-side information architecture
- task-oriented pages
- short conceptual explanations before API details
- verified examples
- explicit diagnostics, failure modes, and quality gates
- bilingual English/Korean content without changing the technical contract

Reference benchmark:
<https://qdrant.tech/documentation/search/search/>

## What Works In The Qdrant Pattern

Qdrant's search page is effective because it is not trying to explain the whole
product on one page. It gives developers a stable map and lets each page answer
a focused operational question.

Observed patterns to adopt:

- The sidebar is organized by developer journey, not by internal source files.
- A core concept page starts with a short explanation, then moves into practical
  API usage.
- Related capabilities are split into sibling pages, for example search,
  filtering, hybrid queries, relevance, and low-latency search.
- Code examples are close to the concept they explain.
- API reference is linked from the guide, but does not replace the guide.
- The visual design is restrained: typography, spacing, navigation, and code
  readability matter more than decorative sections.

Patterns not to copy directly:

- Qdrant is a database product with many SDK languages; graph-tool-call should
  stay Python-first with CLI and JSON artifact examples.
- Qdrant has Cloud and API Reference products; graph-tool-call should keep
  product-specific XGEN material in integration docs, not in the core engine
  contract.

## Documentation Positioning

The public documentation should present graph-tool-call as:

> An engine for building searchable, evidence-backed tool graphs from large tool
> catalogs so LLM agents can retrieve, select, plan, execute, validate, and learn
> safely.

The site should stop optimizing for a single first-screen impression and start
optimizing for repeated developer usage.

## Proposed Information Architecture

### Start

- Overview
- Installation
- Quickstart
- Mental model

Purpose: help a new developer run retrieval against a small OpenAPI source in
the first 10 minutes.

### Tutorials

- OpenAPI search-to-plan

Purpose: give developers a copyable end-to-end path after the quickstart. A
tutorial should connect multiple manual sections into one working workflow
without becoming the reference page for any single API.

### Build Tool Catalogs

- OpenAPI ingestion
- MCP ingestion
- Python function ingestion
- Collection artifact
- Semantic build
- IO contract extraction
- Readiness diagnostics
- Auth readiness

Purpose: explain how raw tool sources become stable tool schemas, contracts,
metadata, graph edges, and validation reports.

### Search And Selection

- Tool graph search
- Retrieval signals
- Candidate expansion
- Evidence output
- Target selection
- Korean and mixed-language search
- Search tuning

Purpose: make retrieval quality explainable. A developer should be able to see
why a tool ranked highly, why another was expanded from it, and why the final
target was selected or not overridden.

### Plan And Execute

- Plan synthesis
- User input slots
- Runner stream events
- Failure taxonomy
- Response synthesis
- Trace metadata

Purpose: document the contract between search results, executable plans, runner
events, and product adapters.

### Learning Loop

- Trace records
- Payload scrubbing
- Suggestions
- Shadow mode
- Promotion policy
- Retrieval and selector boosts

Purpose: explain how usage evidence improves future ranking without training the
LLM or storing raw sensitive payloads.

### Validation

- Benchmark overview
- Search metrics
- BFCL-style methodology
- XGEN scale gates
- Quality Lab
- Release gates

Purpose: separate quality claims from intuition. Every public claim should point
to a reproducible fixture, command, or stored artifact.

### Integrations

- XGEN API Collection
- XGEN Quality Lab
- MCP server
- MCP proxy
- LangChain
- Middleware
- Direct API

Purpose: keep engine docs product-neutral while still documenting the real
adapter paths that users depend on.

### Reference

- Public API
- CLI
- Event schemas
- Report schemas
- Artifact schemas
- Versioning and compatibility

Purpose: provide stable contracts for users who already understand the concepts.

## Sidebar Draft

```text
Overview

Getting Started
  Installation
  Quickstart
  Mental Model

Tutorials
  OpenAPI Search-To-Plan

Build Tool Catalogs
  OpenAPI Ingestion
  MCP Ingestion
  Python Functions
  Collection Artifacts
  Semantic Build
  IO Contracts
  Readiness Diagnostics
  Auth Readiness

Search And Selection
  Tool Graph Search
  Retrieval Signals
  Candidate Expansion
  Evidence Output
  Target Selection
  Korean Search
  Search Tuning

Plan And Execute
  Plan Synthesis
  User Input Slots
  Runner Events
  Failure Taxonomy
  Response Synthesis

Learning Loop
  Trace Learning
  Scrubbing
  Suggestions
  Shadow And Promotion

Validation
  Benchmarks
  BFCL-Style Evaluation
  XGEN Scale Gates
  Quality Lab
  Release Gates

Integrations
  XGEN API Collection
  XGEN Quality Lab
  MCP Server
  MCP Proxy
  LangChain
  Middleware
  Direct API

Reference
  Public API
  CLI
  Event Schemas
  Report Schemas
  Artifact Schemas
  Compatibility
```

## Standard Page Template

Every guide page should use the same shape unless there is a strong reason not
to.

```md
---
title: Tool Graph Search
description: Retrieve a compact, evidence-backed set of tools from a large tool graph.
---

# Tool Graph Search

One-paragraph explanation of the capability.

## When To Use This

- Use it when ...
- Do not use it when ...

## Concept Model

Short explanation of the moving parts.

## Minimal Example

Python example first.

## CLI Example

Equivalent command when useful.

## Inputs

Stable input schema or option table.

## Output

Stable output schema and important fields.

## Evidence And Diagnostics

Explain score breakdown, reason codes, and trace fields.

## Failure Modes

List common failure reasons and what the caller should do.

## Quality Checks

Commands, fixtures, or benchmark gates.

## XGEN Adapter Notes

Only product integration notes. Do not put XGEN-only rules in the engine page.

## API Reference

Links to exact public API entries.
```

## Flagship Page: Tool Graph Search

The first Qdrant-style page should be `Tool Graph Search`, because it is the
clearest bridge between the library's purpose and a developer's first real
question: "How do I find the right tool from a large catalog?"

Required sections:

- What graph search solves for LLM tool catalogs
- Query flow
- Ranking signals
- Candidate expansion
- Evidence output
- Target selector handoff
- Korean and English mixed queries
- Performance and token budget notes
- Troubleshooting bad results
- Quality gates
- Related APIs

Recommended code examples:

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
results = graph.retrieve(
    "환불 가능한 주문 목록을 찾아줘",
    top_k=8,
    include_evidence=True,
)

for result in results:
    print(result.tool.name)
    print(result.score_breakdown)
```

```python
from graph_tool_call.graphify import retrieve_graphify

results = retrieve_graphify(
    graph_json,
    query="find refund-ready orders",
    top_k=8,
    include_evidence=True,
)
```

```bash
graph-tool-call search openapi.json "find refund-ready orders" --top-k 8
```

## Visual Design Principles

Detailed visual shell rules, search behavior, bilingual sidebar requirements,
and implementation phases are now defined in
[`qdrant-style-official-docs-system.md`](qdrant-style-official-docs-system.md).

The visual language should feel like infrastructure documentation:

- Use light mode as the default.
- Prefer white or near-white content surfaces with neutral borders.
- Use one restrained accent color for navigation, links, and primary actions.
- Avoid large dark hero blocks unless the full page has been tested on mobile.
- Avoid gradients, decorative blobs, and oversized marketing sections.
- Use dense but readable spacing for docs pages.
- Keep code blocks prominent, high-contrast, and copyable.
- Preserve Docusaurus defaults where they already solve navigation well.

Suggested palette:

```text
Page background:    #ffffff
Band background:    #f8fafc
Primary text:       #111827
Secondary text:     #475569
Muted text:         #64748b
Border:             #e5e7eb
Accent:             #2563eb
Accent hover:       #1d4ed8
Info tint:          #eff6ff
Warning tint:       #fff7ed
Code background:    #0f172a
Code text:          #e5e7eb
```

## Bilingual Requirements

English is the default locale and Korean is `/ko/`.

Rules:

- Keep page slugs stable across locales.
- Translate explanations, not API names.
- Keep public import paths, option names, event field names, and issue codes in
  English.
- Korean docs can include Korean query examples where search behavior is the
  subject.
- Do not ship English-only pages unless the Korean page intentionally redirects
  or marks itself as pending.

## Implementation Phases

### Phase 1: Documentation System

- Replace the current small sidebar with the proposed manual IA.
- Add empty but navigable pages where needed.
- Add a reusable page frontmatter convention.
- Keep the homepage restrained and make docs navigation the first-class surface.

Exit criteria:

- `cd website && npm run build` passes.
- Both `/docs/` and `/ko/docs/` have the same main structure.
- The homepage no longer carries most of the product explanation burden.

### Phase 2: Flagship Search Page

- Rewrite `Tool Graph Search` as the first high-quality manual page.
- Add verified Python, CLI, and graphify artifact examples.
- Explain retrieval score evidence and target selector handoff.
- Link to benchmark and quality gate docs.

Exit criteria:

- A developer can understand and run retrieval without reading XGEN docs.
- Every code sample is verified against the public package API.

### Phase 3: OpenAPI Collection Manual

- Rewrite OpenAPI collection docs using the same template.
- Cover ingestion, semantic build, IO contract extraction, readiness reports,
  auth readiness, artifact versions, and XGEN adapter boundaries.

Exit criteria:

- A developer can inspect a Swagger/OpenAPI source and understand whether it is
  ready for search, plan, and execution.

### Phase 4: Validation And Learning

- Rewrite benchmark, Quality Lab, and trace learning docs.
- Make public quality claims conservative and reproducible.
- Add release gate documentation.

Exit criteria:

- Benchmark claims link to committed fixtures, commands, or stored artifacts.
- Learning loop docs make privacy and promotion policy explicit.

## Acceptance Criteria

- The documentation should feel useful even if the user skips the homepage.
- A new developer can answer:
  - How do I ingest an OpenAPI source?
  - How does search rank tools?
  - Why did this tool win?
  - How does target selection guard the LLM?
  - Why did execution fail?
  - How do I validate a change?
  - What is XGEN-specific and what is engine-level?
- Public docs should not imply quality claims that are not backed by a test,
  benchmark, or clearly labeled limitation.

## Immediate Next MR

The next implementation MR should be intentionally small:

1. Apply the new sidebar IA.
2. Add missing placeholder pages with clear purpose statements.
3. Rewrite `website/docs/concepts/tool-graph.md` or add
   `website/docs/search/tool-graph-search.md` as the flagship Qdrant-style page.
4. Mirror the structure in Korean.
5. Run `cd website && npm run build`.

This creates the documentation skeleton first. Content can then be improved page
by page without redesigning the whole site each time.
