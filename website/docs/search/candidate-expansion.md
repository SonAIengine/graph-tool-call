---
title: Candidate Expansion
description: Expand retrieved targets with producer tools and graph neighbors when evidence supports it.
---

# Candidate Expansion

Candidate expansion adds related tools after the initial search stage. The most
important expansion is producer discovery: if a target consumes a required field,
the graph can include tools that produce that field.

## Expansion Sources

- deterministic IO contract edges
- OpenAPI links
- manual edges
- promoted run-observed trace edges
- high-confidence semantic links

## Safety Policy

Expansion should improve planning without flooding the LLM catalog. Keep
low-confidence structural edges available for graph inspection, but prefer
strong evidence for execution-oriented candidates.

## Related Pages

- [IO Contracts](../build/io-contracts.md)
- [Plan Synthesis](../plan/plan-synthesis.md)
