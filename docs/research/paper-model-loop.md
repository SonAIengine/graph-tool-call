# Paired B6b/B6c Model Loop

## Purpose

The deterministic B6c experiment showed that contract projection can expose a
useful fifth tool under the same 2,048-token catalog budget. That result does
not show whether a model can use the additional tool. This harness evaluates
the next causal link without changing retrieval:

```text
frozen B6b or B6c catalog
-> model selects target and supporting tools
-> complete schemas are hydrated
-> model emits an ordered plan
-> plan and arguments are validated
```

The input is an already validated deterministic paper artifact. The model-loop
runner never recomputes rankings, and it rejects a case when the B6b and B6c
rankings differ. The only experimental difference is the selection-time schema
representation and the candidates that fit under the frozen token budget.

## Frozen Protocol

The policy revision is `paper-two-pass-tool-selection-v1`.

Pass 1 gives the model:

- the original user query;
- the exact token-budget catalog reconstructed from the deterministic artifact;
- complete B6b schemas or B6c's recorded `full`/`contract_projected` mix.

The model returns:

```json
{
  "target_tool": "final operation name",
  "supporting_tools": ["producer operation name"]
}
```

Pass 2 hydrates every selected name from the source snapshot. Projection is
never accepted as an execution contract. The artifact records both the
complete ToolSchema SHA-256 and the full request-schema view used for argument
validation. To avoid placing hundreds of irrelevant response leaves into the
planner context, the model sees a bounded contract view containing response
fields compatible with inputs of the selected tools. This view is derived only
after source hydration under `paper-hydrated-contract-view-v1`; it is not used
for retrieval or target selection. Any unknown selected name blocks planning.
The model then returns:

```json
{
  "final_target": "final operation name",
  "plan": [
    {
      "tool": "operation name",
      "arguments": {},
      "bindings": {
        "inputField": {
          "from_tool": "earlier operation name",
          "path": "result.field"
        }
      },
      "missing_required_inputs": []
    }
  ]
}
```

Every required parameter must be represented by a literal argument, an
earlier-step binding, or `missing_required_inputs`. The harness validates names,
argument keys, simple declared types, enum values, binding direction, binding
paths against source `api_contract.produces`, required input accounting, and
final-target position. It does not execute HTTP requests.

Expected targets, producer annotations, alternatives, and held-out labels are
used only after both model calls to calculate metrics. They are never included
in either prompt.

## Run

First generate or select a clean deterministic artifact:

```bash
make paper-contract-projection
```

Then run the paired model loop against an OpenAI-compatible endpoint:

```bash
BASELINE_ARTIFACT=/tmp/graph-tool-call-paper-contract-projection.json \
MODEL=Qwen/Qwen3.6-27B-FP8 \
MODEL_REVISION=e89b16ebf1988b3d6befa7de50abc2d76f26eb09 \
PROVIDER=openai-compatible \
LLM_URL=http://localhost:8000/v1 \
REPEATS=1 \
make paper-model-loop
```

For development, use `--case-id` or `--limit` through the module CLI. The
publication candidate uses three paired repeats and a clean commit:

```bash
poetry run python -m benchmarks.paper_model_loop.run \
  --baseline-artifact /tmp/graph-tool-call-paper-contract-projection.json \
  --model Qwen/Qwen3.6-27B-FP8 \
  --model-revision e89b16ebf1988b3d6befa7de50abc2d76f26eb09 \
  --provider openai-compatible \
  --llm-url http://localhost:8000/v1 \
  --repeats 3 \
  --out /tmp/graph-tool-call-paper-b6c-model-loop.json
```

The endpoint URL is redacted before it enters the artifact. API key values,
request headers, and environment values are never persisted.

## Metrics

Each B6b/B6c condition records:

- selector target accuracy;
- required-producer and required-tool recall;
- all-required-selected rate;
- hallucination-free selection rate;
- full-schema hydration success;
- plan tool validity;
- argument-schema validity;
- required-input accounting;
- final-target consistency;
- end-to-end structural validity;
- selection/planning tokens, calls, and latency.

The artifact reports paired B6c-minus-B6b improvement, regression, and tie
counts plus bootstrap confidence intervals. Protocol gates require identical
B6b/B6c rankings and catalog-budget compliance for every case.

## Failure Taxonomy

Stable reason codes separate:

- selection model/API failure;
- invalid selector JSON or missing target;
- tool names outside the frozen catalog;
- full-schema hydration failure;
- planning model/API failure;
- invalid plan JSON;
- non-hydrated plan tools;
- unknown or mistyped arguments;
- invalid backward/unknown bindings;
- unaccounted or invalid missing inputs;
- final-target mismatch.

## Interpretation Boundary

An improvement supports the claim that contract projection makes useful
evidence-admitted tools actionable for a frozen model under a fixed catalog
budget. It does not establish execution success, generalize to held-out
families, or replace the budgeted full-catalog LLM selector baseline. HTTP
execution and B0-L remain separate experiments.
