# Trace Learning Loop

The trace learning loop improves retrieval and planning from execution history
without fine-tuning the LLM.

## Policy

The default policy is:

```text
observe -> shadow -> promote
```

One success is recorded as evidence, not immediately trusted as production
ranking truth. Repeated success or Quality Lab validation can promote it.

## What Is Stored

Learning records store compact, scrubbed facts:

- normalized query and attempt chain
- selected target and LLM target
- plan path
- success or failure reason
- latency and selector signals
- derived trace edges

Raw request/response bodies, tokens, cookies, API keys, and obvious personal
data are not stored.

## How It Helps

Promoted suggestions can add low-weight evidence for:

- target preference
- successful plan path
- field mapping
- data-flow edge
- context or enum mapping candidates

