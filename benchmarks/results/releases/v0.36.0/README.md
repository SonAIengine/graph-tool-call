# v0.36.0 release evidence

`dependency-chain-evidence.json` is a deterministic, case-level artifact for
the public dependency-expansion claim. It is generated from the checked-in
commerce OpenAPI fixture and ground truth. No LLM or external API is used.

Regenerate and verify it with:

```bash
make launch-evidence
make launch-evidence-check
```

The artifact records fixture hashes, the replay command, every expected target
and producer, target-only candidates, graph-expanded candidates, and the
before/after metrics. Its seven curated cases are a regression suite, not a
population-level model accuracy claim.
