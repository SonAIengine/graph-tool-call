# Quality Gates

Quality gates keep search and planning improvements measurable.

## Development Loop

Use quick deterministic checks during implementation:

```bash
make quick
poetry run pytest tests/test_graphify_metadata.py tests/test_openapi_readiness.py -q
```

Use larger OpenAPI and LLM checks only when retrieval, selector, or plan logic
changes materially.

## Suggested Gates

For large OpenAPI collections:

- semantic action known rate
- primary resource assigned rate
- path/module assigned rate
- search Hit@K
- plan target hit rate
- execute read success rate
- structured failure classification rate
- uncaught server error count

The goal is not to make every API call succeed in CI. The goal is to make every
success and failure explainable.

