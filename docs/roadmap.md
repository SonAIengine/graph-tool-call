# graph-tool-call Roadmap

> Updated: 2026-08-09
> Baseline: `main` after the 0.38 trace-observability changes
> Scope: provider-neutral tool ingestion, retrieval, planning contracts, and
> evidence. Product auth, model-provider lifecycle, and UI remain outside the
> library.

## Current Position

graph-tool-call is no longer only a BM25 tool retriever. The current public
surface covers the path from heterogeneous API/tool metadata to an auditable,
planner-facing candidate bundle.

| Layer | Current capability |
| --- | --- |
| Ingest | OpenAPI 2/3.0/3.1, GraphQL introspection, MCP tools, Python functions, structured catalogs |
| Contract | request/response preservation, auth/security metadata, `consumes`/`produces`, links, response envelopes |
| Graph | structural, API-contract, OpenAPI-link, manual, LLM-curated, and run-observed evidence |
| Search | BM25, graph expansion, optional embedding/reranking, Korean tokenization, evidence output |
| Selection | deterministic target guard, sibling control, target/producer role separation |
| Planning | dependency closure, contract-projected schemas, token-budget admission, `PathSynthesizer` |
| Execution | `PlanRunner.run_stream`, structured events/errors, host-supplied execution adapters |
| Learning | scrubbed trace records and observe-shadow-promote suggestions |
| Operations | OpenAI/Anthropic middleware, LangChain v1 middleware, MCP server/proxy, Docker/Kubernetes |
| Validation | Python 3.10-3.14 CI, 1,200+ tests, deterministic release evidence, public research harnesses |

The old roadmap described several of these features as missing. It is retained
in git history rather than repeated here as current work.

## Product Priorities

### P0. Release and public-surface integrity

**Goal:** a clean install should match the README, docs, package metadata, and
published evidence.

- keep the README short and executable;
- freeze a versioned release-evidence artifact;
- verify wheel/sdist, public examples, Docker startup, and MCP initialize/search;
- keep GitHub Release, tag, CHANGELOG, PyPI, and documentation on one version;
- publish only claims backed by committed case-level output.

**Exit gate:** `make release-check`, clean-wheel smoke, container smoke, and the
Python version matrix all pass for the release commit.

### P1. Real ecosystem compatibility

**Goal:** move important integrations from protocol compatibility to repeatable
application-level smoke tests.

1. OpenAI Agents SDK through remote MCP.
2. PydanticAI `MCPToolset` through remote MCP.
3. Google ADK `McpToolset` through remote MCP.
4. One account-owned AWS AgentCore or Microsoft Foundry gateway smoke.
5. A compatibility manifest recording package version, transport, scenario,
   result, and last verification date.

Framework-specific execution policy stays in the framework. The library should
not copy provider auth or agent lifecycle code.

### P2. Observability and explainability

**Goal:** answer "why was this tool selected, expanded, admitted, or rejected?"
without reconstructing the engine offline.

- stable retrieval trace schema for score channels and rank transitions;
- target-selector and dependency-closure spans;
- token-budget admission decisions and dropped-schema reasons;
- OpenTelemetry export behind an optional dependency;
- secret-safe CLI trace output and MCP request correlation;
- latency histograms for ingest, retrieve, expand, select, and plan.

**Exit gate:** one query can be replayed from a scrubbed trace and every final
candidate has a machine-readable reason.

### P3. Dynamic-catalog performance

**Goal:** keep latency predictable when tools and MCP backends change at
runtime.

- incremental BM25 and optional embedding add/remove;
- cached category/module indexes with explicit invalidation;
- backend reconnect and tool mutation handling;
- large-catalog memory and p50/p95 latency gates;
- deterministic serialization after incremental updates.

Optimization work starts from profiles, not a Rust rewrite. Native extensions
are considered only after a measured Python bottleneck remains.

### P4. Cross-source dependency quality

**Goal:** connect fields and workflows across independently owned specs and MCP
servers without domain-specific hardcoding.

- provenance-preserving cross-source contract matching;
- collision-safe tool identity and human-readable aliases;
- direct/required edges before indirect/optional edges;
- uncertainty and unresolved-field diagnostics;
- negative controls against generic IDs, paging, auth, and context fields.

**Exit gate:** improvements reproduce on multiple unseen API families, not only
XGEN or one commerce fixture.

### P5. Security and governance

**Goal:** make enterprise deployment failures explicit before model execution.

- tool-schema mutation fingerprints and provenance;
- prompt-injection and suspicious-description diagnostics;
- annotation-aware exposure policy;
- executable vs metadata-only capability gates;
- policy hooks for destructive, open-world, and untrusted tools;
- no raw secrets in graph, trace, learning, or benchmark artifacts.

The engine reports facts and policy signals; the host application makes the
authorization decision.

## Research Priorities

The canonical experiment rules remain in
[`paper-readiness-design.md`](research/paper-readiness-design.md). The immediate
research sequence is:

1. audit BFCL V4, MCP-Atlas, Toolathlon, ToolRet, Re-Invoke, and TGR licenses and
   reproducibility boundaries;
2. run and review the frozen three-repeat B0-L vs B6c train/dev experiment;
3. complete contamination-sensitivity and prospective power analyses;
4. run the frozen full ablation matrix on train/dev;
5. obtain an independent protocol review;
6. open the held-out split only after the preregistered gates pass.

### Main research hypothesis

The paper is about **model-independent retrieval middleware**, not LLM
fine-tuning. The candidate contribution is the combination of:

- normalized tool contracts from heterogeneous sources;
- explicit target discovery separated from prerequisite completion;
- typed graph evidence;
- token-budgeted contract projection;
- model-loop evaluation with full-schema hydration before argument generation.

Trace learning remains a controlled follow-up unless its causal contribution is
isolated with shadow and promotion gates.

## Non-Goals for the Next Release

- training or fine-tuning an LLM;
- embedding XGEN-specific DB, auth, cookie, SSE, or user-ID logic;
- becoming a general model-provider router;
- exposing a public unauthenticated MCP execution endpoint;
- claiming official BFCL or state-of-the-art results without parity evidence;
- direct TypeScript/Java SDKs before MCP adoption data justifies them.

## Release Sequence

| Release | Focus | Required evidence |
| --- | --- | --- |
| 0.37 | adoption readiness and public-surface cleanup | release evidence, framework adapter tests, Docker/MCP smoke |
| 0.38 | trace schema and optional OpenTelemetry | replay test, secret scrub, latency overhead (delivered) |
| 0.39 | ecosystem smoke matrix and dynamic-catalog profiling | real framework runs, p50/p95 scale report |
| 0.40 | cross-source dependency hardening | unseen-family paired evaluation and negative controls |

Version numbers after 0.38 are planning targets, not commitments. A release is
cut only when its evidence gate passes.

## Working Rules

1. Use fast deterministic tests for each edit; run model loops only at a frozen
   release or paper gate.
2. Do not tune against the held-out split.
3. Keep product-neutral logic in graph-tool-call and application adapters in
   their owning repositories.
4. Add public API fields additively unless a major version explicitly permits a
   breaking change.
5. Preserve raw human metadata and manual/trace evidence during rebuilds.
6. Prefer structured parsers and schemas over string heuristics.
7. Record limitations next to every benchmark claim.

## References

- [Official documentation](https://sonaiengine.github.io/graph-tool-call/)
- [Benchmark results](benchmarks.md)
- [Paper readiness protocol](research/paper-readiness-design.md)
- [Validation loop](research/validation-loop.md)
- [External retrieval comparison](research/external-tool-retrieval-comparison.md)
- [Release checklist](release-checklist.md)
