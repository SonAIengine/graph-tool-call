# Qdrant-Style Official Docs System

## Goal

Raise the graph-tool-call public documentation from a styled project site to a
serious developer documentation product. The target is not to copy Qdrant's
brand, but to match the qualities that make its documentation useful:

- a stable manual-first layout
- fast page scanning
- strong code readability
- search as a first-class navigation tool
- clear separation between guide, tutorial, integration, and reference content
- mobile pages that remain readable without dark-mode contrast accidents

Reference page:
<https://qdrant.tech/documentation/search/search/>

## What The Qdrant Pattern Gets Right

The Qdrant search page works because it behaves like a product manual. It gives
the reader a predictable shell first, then lets the content answer one focused
question.

Adopt these patterns:

- Top navigation separates product areas from documentation content.
- The documentation sidebar is a durable map organized by user jobs.
- The page title is direct and specific.
- The opening paragraph explains the concept without becoming a marketing hero.
- A practical API section appears early.
- Dense examples sit close to the concept they explain.
- Related pages are split into sibling topics instead of one very long page.
- API reference is linked from the guide, but guide pages are still readable on
  their own.
- Visual emphasis comes from spacing, type, borders, tables, and code blocks,
  not decorative artwork.

Avoid copying these parts directly:

- Qdrant documents a database with many SDK languages. graph-tool-call should
  stay Python-first and add CLI/JSON examples only when useful.
- Qdrant has a Cloud product and hosted API reference. graph-tool-call should
  keep PyPI, GitHub Pages, XGEN integration, and engine reference distinct.
- Qdrant's brand colors should not be reused. The graph-tool-call palette should
  be neutral, accessible, and technical.

## Current Gap

The current site has improved IA and stronger manual pages, but it still lacks
the last layer that makes a docs site feel official:

- The home page is still closer to a portal landing page than a documentation
  product shell.
- Local search exists, but search quality and bilingual result checks must stay
  part of the docs acceptance flow.
- The visual system is tokenized, but not strict enough about contrast,
  spacing, typography, and mobile behavior.
- Sidebar category labels and generated index pages must remain localized in
  the Korean locale.
- Core pages are uneven: some are full guides, while others are placeholders.
- Code examples are readable, but not yet standardized around multi-tab
  patterns, request/output pairs, and copy-friendly blocks.
- Reference pages are manually written and not yet connected to generated or
  validated public API surfaces.

## Product Principle

The docs should be optimized for repeated use by a developer who is already
trying to solve a real problem:

> I have a large tool catalog. How do I build it, search it, select a target,
> plan execution, validate quality, and debug failures?

That means every visible page should reduce time to the next correct action.

## Design Target

The target experience is a manual, not a brochure:

> A developer should be able to land on any page, understand what layer they are
> working in, copy a minimal example, inspect the returned evidence, and know
> which validation gate proves the behavior.

This changes the definition of "good design" for this site. Visual polish is
necessary, but the primary design artifact is a repeatable reading and working
system.

## Qdrant Pattern Mapping

Qdrant's search documentation is useful because it puts a large technical
surface inside a predictable manual shell: stable navigation, task-oriented
sidebar categories, compact concept text, API tables, and code examples close to
the section they explain. graph-tool-call should map those strengths to its own
domain instead of copying the visual brand.

| Qdrant docs pattern | graph-tool-call equivalent | Design decision |
| --- | --- | --- |
| Product docs header | `Docs`, `Search`, `OpenAPI`, `Quality`, `Reference` | Keep the top nav short and task-oriented. |
| Deep user manual sidebar | Build, Search, Plan, Learning, Validation, Integrations, Reference | Sidebar is the primary product map. |
| Early API section | Public helper import, minimal Python call, output shape | Every task guide gets a copyable first example. |
| Multi-language code blocks | Python-first, CLI and JSON output when helpful | Do not add fake SDK tabs. |
| Search and filtering manual split | Retrieval, evidence, candidate expansion, target selection | Split search into operational subtopics. |
| Database metrics and parameters | Quality gates, readiness reports, selector signals | Explain how to prove quality, not only how to call APIs. |
| External API reference link | Public API and artifact schema pages | Link reference from guides, but guides must stand alone. |

## User Journeys

The documentation must support five primary jobs without requiring the reader to
guess which subsystem owns the answer.

| Journey | Entry page | Must answer |
| --- | --- | --- |
| Build a catalog from Swagger/OpenAPI | Build Tool Catalogs -> OpenAPI Ingestion | What source formats work, what artifact is produced, what diagnostics appear. |
| Follow the full build/search/plan workflow | Tutorials -> OpenAPI Search-To-Plan | How inspection, artifact build, retrieval evidence, target selection, and plan synthesis connect. |
| Improve tool search quality | Search And Selection -> Tool Graph Search | Which signals rank tools, how evidence is returned, how to tune Top-K. |
| Stop wrong LLM target choices | Search And Selection -> Target Selection | When deterministic selection can override, when it only reports ambiguity. |
| Execute and debug a plan | Plan And Execute -> Plan Synthesis | What inputs are required, what failure reason means, how runner events are shaped. |
| Make the system improve over time | Learning Loop -> Trace Learning | What trace data is saved, how suggestions are scrubbed, when promotion happens. |

Secondary jobs:

- confirm public API stability
- run CLI diagnostics
- integrate with XGEN, MCP, LangChain, or middleware
- verify benchmark and Quality Lab claims
- read Korean docs without falling back to partial English placeholders

## Documentation Shell

### Header

The header should feel like a compact docs product header, not a marketing nav.

Required items:

- Brand: `graph-tool-call`
- Docs navigation: `Docs`, `Search`, `OpenAPI`, `Quality`, `Reference`
- Search input or search button
- Locale switcher
- GitHub link
- PyPI link

Behavior:

- Keep the header height stable on desktop and mobile.
- On mobile, collapse links behind the Docusaurus menu and keep search
  available from the menu or a visible search button.
- Do not let translated labels wrap inside buttons.

### Left Sidebar

The sidebar remains the primary map. It should follow the manual IA introduced
in `developer-documentation-manual.md`, with two refinements:

- Translate generated category labels for Korean.
- Keep generated index pages short and task-based, not empty category pages.

Category order:

```text
Overview
Getting Started
Tutorials
Build Tool Catalogs
Search And Selection
Plan And Execute
Learning Loop
Validation
Integrations
Reference
```

### Right Table Of Contents

The right TOC should be useful for long operational pages:

- show H2 and H3 only
- use small, readable text
- keep active item visible
- avoid aggressive indentation
- hide on mobile

### Search

Search should be treated as a first-class manual feature before the
documentation is considered official.

Preferred implementation:

- Use a Docusaurus-compatible local search plugin for GitHub Pages.
- Index English and Korean pages.
- Exclude build artifacts and generated static files.
- Include `llms.txt` as a compact navigation aid, but do not treat it as a
  replacement for human-facing search.

Search acceptance:

- Query `OpenAPI contract` finds IO contract and OpenAPI ingestion pages.
- Query `target selection` finds the target selection page.
- Query `auth readiness` finds Quality Lab and auth readiness pages.
- Query `한글 검색` finds Korean search docs.

## Content Contract

Official documentation quality depends on API correctness as much as visual
polish. Any page that includes executable code must use the public contract that
is currently supported by the library.

Required checks:

- `retrieve_graphify()` examples treat the return value as a response object
  with `results`, `subgraph_text`, `intent`, and `stats`.
- retrieval rows use `name`, `tool`, `score`, `score_breakdown`,
  `edge_evidence`, and `semantic_evidence`.
- selector examples use `candidate_evidence` only for
  `select_target_candidate()` output.
- `PathSynthesizer.synthesize()` examples use the keyword-only
  `target`, `goal`, and `entities` arguments.
- persisted collection examples load through `ToolGraph.load()` before calling
  retrieval APIs.

Do not publish a docs design MR unless `npm run typecheck`, `npm run build`,
and a small mobile overflow check pass.

## Visual System

### Direction

Use a calm infrastructure-docs look:

- light mode by default
- white page background
- very light gray section bands
- dark ink text
- restrained teal/blue accents
- no dark hero as the default first impression
- no gradients, decorative blobs, or oversized marketing blocks

### Palette

Use separate tokens for text, surfaces, borders, semantic states, and code.

```text
Page background:       #ffffff
Subtle band:           #f6f8fb
Raised surface:        #ffffff
Primary text:          #111827
Secondary text:        #475569
Muted text:            #64748b
Border:                #d8dee8
Hairline border:       #edf1f5
Primary accent:        #0f766e
Primary accent hover:  #115e59
Link accent:           #1d4ed8
Info tint:             #eff6ff
Success tint:          #ecfdf5
Warning tint:          #fff7ed
Danger tint:           #fef2f2
Code background:       #0b1020
Code header:           #111827
Code text:             #d8e3f4
Inline code bg:        #eef2f7
```

Rules:

- Primary buttons must pass contrast against their background.
- Secondary buttons must not look disabled.
- Dark mode may exist, but it must be visually tested. Light mode remains the
  first-visit default.
- Do not use blue as the only visual language. Use blue for links/info and teal
  for primary action.

### Typography

Use documentation-scale type, not landing-page type.

- Page H1: `2.1rem` to `2.7rem` on desktop, `1.85rem` on mobile.
- H2: `1.45rem` to `1.75rem`.
- Body: `0.96rem` to `1rem`.
- Line height: `1.65` to `1.75`.
- Letter spacing: `0`.
- Code: `0.86rem` to `0.92rem`, depending on viewport.

Rules:

- Avoid viewport-scaled hero text for docs pages.
- Keep Korean line length slightly shorter than English where possible.
- Never let CTA text wrap into awkward stacked syllables on mobile.

### Layout Width

Recommended desktop layout:

```text
left sidebar: 280px
content:      720-820px
right TOC:    220px
page gutter:  24-32px
```

Home page can use a wider grid, but guide pages should prioritize reading.

### Cards

Cards should be used only for navigation groups, status summaries, and repeated
items. They should not be nested.

Card rules:

- radius: 8px or less
- border: neutral
- hover: border color and subtle shadow only
- no decorative gradients
- fixed minimum height only when repeated cards need alignment

### Code Blocks

Code blocks should become a core visual asset.

Required behavior:

- high contrast
- copy button available through Docusaurus
- language label when useful
- request/output pairs where the output teaches the contract
- tabs only when the alternatives are genuinely useful

Preferred tab sets:

- Python / CLI / JSON
- Python / XGEN Adapter / Output
- Search / Plan / Execute for workflow pages

## Page Templates

### Documentation Page Layout Contract

Every important documentation page should be readable as an independent manual
entry. The homepage may introduce the product, but no guide page should depend
on marketing context.

Required page shell:

```text
H1
  one-paragraph scope statement
  "Use this when..." or "This page covers..."

Early example
  minimal Python or CLI call
  compact output shape

Operational sections
  inputs
  outputs
  evidence and diagnostics
  failure modes

Reference bridge
  public API or schema link
  validation gate link
  related pages
```

Content rules:

- Explain product-neutral engine behavior before XGEN adapter behavior.
- Keep XGEN examples in integration or validation pages unless the core API
  explicitly supports the same contract.
- Put reason codes, event types, JSON keys, and public imports in tables.
- Put long narrative before examples only when the concept cannot be understood
  from code.
- Include at least one expected output snippet for each core workflow page.
- Add "Failure modes" to pages that users will debug under pressure.
- Add "Validation" to pages that make quality or performance claims.
- Do not publish benchmark-like statements without a command, fixture, date, or
  explicit limitation.

### Concept Page

Use for mental model, tool graph, semantic build, trace learning.

```md
# Title

One-paragraph concept definition.

## Why It Exists
## How It Works
## What It Produces
## Example
## Failure Modes
## Related Pages
```

### Task Guide

Use for OpenAPI ingestion, search, target selection, Quality Lab.

```md
# Title

Outcome-focused opening paragraph.

## When To Use This
## Minimal Example
## Inputs
## Output
## Evidence And Diagnostics
## Failure Modes
## Quality Checks
## Related APIs
```

### Reference Page

Use for API, CLI, event schemas, report schemas.

```md
# Title

Short scope note.

## Stability
## Import Or Command
## Parameters
## Return Shape
## Version Notes
## Examples
```

### Integration Page

Use for XGEN, MCP, LangChain, middleware.

```md
# Title

What layer this integration owns.

## Responsibility Split
## Setup
## Data Flow
## Auth And Safety
## Observability
## Failure Modes
## Adapter Boundary
```

## Homepage Redesign V3

The homepage should stop trying to carry the whole story. It should behave like
the front door to the manual.

First viewport:

- compact title: `Graph-based tool retrieval for large LLM tool catalogs`
- one-sentence product definition
- primary CTA to Quickstart
- secondary CTA to Tool Graph Search
- compact install command
- minimal Python example with output shape
- no dark hero block
- no disabled-looking secondary button
- no decorative visual that does not teach the product

Second viewport:

- six task routes: Build, Search, Select, Plan, Validate, Learn
- each route links to the strongest guide page
- route cards use one-line outcomes, not marketing copy

Third viewport:

- engine flow: Ingest -> Contract -> Search -> Select -> Plan -> Learn
- show one concrete artifact per stage: `ToolSchema`, `api_contract`,
  `score_breakdown`, `target_selector`, `runner events`, `learning suggestions`
- keep this as a slim manual map, not large decorative cards

Fourth viewport:

- validation gates
- benchmark caveat and links to repeatable commands
- XGEN scale gate link
- Quality Lab link

Wireframe:

```text
header: brand | Docs | Search | OpenAPI | Quality | Reference | search | lang | GitHub | PyPI

hero:
  left: title, definition, CTAs, route chips
  right: install + minimal retrieval example + compact output

manual routes:
  Build catalog | Search tools | Select target | Plan execution | Validate quality | Learn from traces

engine map:
  Ingest -> Contract -> Retrieve -> Select -> Plan/Run -> Learn

validation:
  Search gates | OpenAPI readiness | Plan/Execute gates | Learning safety
```

Footer:

- Docs
- Validation
- Reference
- Project links

Homepage acceptance:

- On a 390px viewport, the title, definition, two CTAs, and install command fit
  before the first long scroll.
- The secondary CTA must look clickable in both light and dark mode.
- The user can reach Quickstart, OpenAPI Ingestion, Tool Graph Search, Quality
  Lab, and Public API in one click.
- The hero code example must be valid against current public imports.

## Content Completion Priorities

To reach official-docs quality, page depth matters more than adding more pages.

Priority 1:

- Tool Graph Search
- OpenAPI Ingestion
- IO Contracts
- Target Selection
- Quality Lab

Priority 2:

- Semantic Build
- Readiness Diagnostics
- Plan Synthesis
- Runner Events
- Trace Learning
- Public API

Priority 3:

- MCP Server
- MCP Proxy
- LangChain
- Middleware
- CLI
- Report Schemas

## Bilingual Policy

English is canonical for API contracts. Korean should be a real translation of
developer guidance, not a partial mirror.

Rules:

- Keep slugs identical.
- Translate titles, descriptions, and explanations.
- Keep import names, field names, reason codes, and CLI flags in English.
- Korean pages can include Korean user queries.
- Korean sidebar category labels must be localized.
- Missing Korean pages should not silently show English once the docs are
  publicly announced.

## Implementation Plan

### MR 1: Shell And Visual System

- Add local search.
- Redesign homepage to docs-front-door layout.
- Refine CSS tokens and button contrast.
- Tune Docusaurus docs typography, sidebar, TOC, tables, admonitions, and code
  blocks.
- Add Korean sidebar/category labels.
- Verify desktop and mobile screenshots.

Exit criteria:

- `cd website && npm run typecheck`
- `cd website && npm run build`
- desktop and mobile screenshots show no overflow or low-contrast buttons
- search queries from the acceptance list return useful pages

Status:

- Mostly implemented in the current docs PR.
- Preserve the search plugin, bilingual build, GitHub Pages workflow, and shell
  typography while redesigning the homepage again.

### MR 2: Qdrant-Level Home And Manual Front Door

- Replace the current portal-style homepage with the V3 manual front door.
- Move the first CTA to Quickstart and second CTA to Tool Graph Search.
- Add a concrete output snippet beside the minimal retrieval code.
- Add six task routes: Build, Search, Select, Plan, Validate, Learn.
- Add a compact artifact-based engine map.
- Add validation gates in the homepage body.
- Re-test 390px mobile, desktop, light mode, and dark mode.

Exit criteria:

- The first viewport looks like a developer manual, not a marketing hero.
- Primary and secondary buttons pass contrast and look enabled.
- No homepage card overflows in Korean.
- The code example imports and method names are accurate.

### MR 3: Core Manual Depth

- Add a tutorial layer for end-to-end workflows that should not live entirely
  in Quickstart or Reference.
- Expand Semantic Build.
- Expand Readiness Diagnostics.
- Expand Plan Synthesis.
- Expand Runner Events.
- Expand Trace Learning.
- Expand Public API.

Exit criteria:

- Every priority 1 and priority 2 page follows a page template.
- Every code example is verified or clearly marked as schema-only.

### MR 4: Reference And Release Polish

- Add generated or semi-generated public API tables where practical.
- Tighten CLI reference.
- Add versioning and release notes path.
- Add public benchmark claim policy.

Exit criteria:

- A new user can navigate from problem to API reference in two clicks.
- Public claims link to commands, fixtures, or limitations.

### MR 5: Docs Operations

- Add a small docs QA script or checklist for:
  - build
  - search index presence
  - route status
  - mobile overflow
  - dark-mode CTA contrast
- Document how to publish GitHub Pages and verify the deployed URL.
- Add a release checklist item: public docs must match current package version.

Exit criteria:

- The docs can be changed and verified without relying on visual intuition.
- A docs-only PR has repeatable checks comparable to code PRs.

## Acceptance Checklist

The docs are not considered Qdrant-level until these checks pass:

- Header search exists and works for English and Korean.
- Homepage first viewport is clear on a 390px mobile screen.
- No primary/secondary CTA has disabled-looking contrast.
- Docs pages read well without visiting the homepage.
- Sidebar labels are localized in Korean.
- Core pages use consistent templates.
- Code blocks are readable on mobile and desktop.
- Target selection, auth readiness, Quality Lab, and learning pages explain
  failure modes as first-class concepts.
- Validation pages do not overclaim benchmark results.
- `llms.txt` points to the same main routes humans see.
