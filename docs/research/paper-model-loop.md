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
MODEL=qwen3.6-27b \
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
  --model qwen3.6-27b \
  --model-revision e89b16ebf1988b3d6befa7de50abc2d76f26eb09 \
  --provider openai-compatible \
  --llm-url http://localhost:8000/v1 \
  --repeats 3 \
  --out /tmp/graph-tool-call-paper-b6c-model-loop.json
```

Repeat statistics can be recomputed from the saved artifact without loading or
calling the model:

```bash
ARTIFACT=/tmp/graph-tool-call-paper-b6c-model-loop.json \
BOOTSTRAP_RESAMPLES=10000 \
OUT=/tmp/graph-tool-call-paper-b6c-model-loop-analysis.json \
make paper-model-loop-analysis
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
counts plus both repeated-row and original-case-clustered bootstrap confidence
intervals. Publication inference uses the clustered interval: repeat deltas
are averaged within each `original_case_id` before resampling. Protocol gates
require identical B6b/B6c rankings and catalog-budget compliance for every
case.

## Validated Development Run

The clean single-repeat train/dev run used commit
`1b1f9f4e791441eee37407182bb7ac4e4af58789`, deterministic input artifact
`exp-c7f4b09c92ca16f14fafde76`, and
`Qwen/Qwen3.6-27B-FP8` revision
`e89b16ebf1988b3d6befa7de50abc2d76f26eb09`. The model was served as
`qwen3.6-27b` by vLLM `0.24.0` with two RTX 5090 GPUs, tensor parallel size
two, a 32,768-token context, FP8 model weights, BF16 KV cache,
FlashAttention, and CUTLASS FP8 kernels. Thinking was disabled and paired
conditions used the same derived seed.

Artifact `exp-33319da455a89aa3e89312b3` (run
`run-11c41a69e9cbe8f1b58e`) contains 29 paired cases and 58 condition records.
It passed schema validation with `git_dirty=false`, identical B6b/B6c ranking
for every pair, and 100% catalog-budget compliance.

| Model-loop metric | B6b | B6c | Paired change |
|---|---:|---:|---:|
| selector target accuracy | 0.8966 | 0.8966 | 0.0000 |
| selector producer recall | 0.8966 | 0.9310 | +0.0345 |
| selector required-tool recall | 0.8621 | 0.8793 | +0.0172 |
| all required selected | 0.7931 | 0.8276 | +0.0345 |
| full-schema hydration success | 0.9655 | 0.9655 | 0.0000 |
| argument-schema validity | 0.8966 | 0.8966 | 0.0000 |
| end-to-end structural validity | 0.6897 | 0.7241 | +0.0345 |

Exactly one pair improved and none regressed. For
`kubernetes-dev-pod-logs-en`, B6b selected the target but chose
`readCoreV1NamespacedPodStatus` as support. B6c exposed the previously
budget-excluded `listCoreV1NamespacedPod`; the same model selected it, hydrated
its complete schema, bound its pod name and namespace outputs to
`readCoreV1NamespacedPodLog`, and passed structural plan validation.

This is mechanism evidence, not a final significance claim. The 95% paired
bootstrap intervals for producer recall and end-to-end validity were both
`[0.0000, 0.1034]`. They include zero because only one of the 29 development
cases used a projected schema. The three-repeat publication candidate below
tests repeat stability; the still-sealed held-out evaluation remains a
separate publication gate.

## Validated Three-Repeat Publication Candidate

The clean three-repeat train/dev run used merged `main` commit
`406f7e127099f68a497eaae4adb26e5ff719ebdd`, the same deterministic input
artifact and model revision as the development run, and 10,000 bootstrap
resamples. Artifact `exp-af3e63a6328a3e3ed981c898` (run
`run-04a25f625f4a4a89cf53`) contains 29 unique cases, three repeats, 174
condition records, and 87 B6b/B6c pairs. Its SHA-256 is
`e82bc9876a8ccf8c0e1a234508e7174156ecacde0a2575c4edc38e6c4755d221`.

Offline clustered analysis
[`analysis-a1b9002abae40581fc8691f8`](../../benchmarks/results/paper/b6c-model-loop-publication-r3-clustered-analysis.json)
references that exact artifact and performed zero model calls. The analysis
report SHA-256 is
`e176706d589c44fdb829069dea04ac587efb07874f5c7e29c1591571e120e2e4`.

The artifact passed schema validation with `git_dirty=false`, exact source and
dependency-lock hashes, 100% B6b/B6c ranking identity, 100% catalog-budget
compliance, and `held_out_accessed=false`. The model-serving configuration was
unchanged from the development run.

| Model-loop metric | B6b | B6c | Paired change | 95% case-clustered CI |
|---|---:|---:|---:|---:|
| selector target accuracy | 0.8966 | 0.8966 | 0.0000 | [0.0000, 0.0000] |
| selector producer recall | 0.8966 | 0.9310 | +0.0345 | [0.0000, 0.1034] |
| selector required-tool recall | 0.8621 | 0.8793 | +0.0172 | [0.0000, 0.0517] |
| all required selected | 0.7931 | 0.8276 | +0.0345 | [0.0000, 0.1034] |
| full-schema hydration success | 0.9655 | 0.9655 | 0.0000 | [0.0000, 0.0000] |
| argument-schema validity | 0.8621 | 0.8621 | 0.0000 | [0.0000, 0.0000] |
| required-input accounting | 0.9310 | 0.9310 | 0.0000 | [0.0000, 0.0000] |
| end-to-end structural validity | 0.6552 | 0.6897 | +0.0345 | [0.0000, 0.1034] |

All three repeats produced the same aggregate effectiveness values. The same
`kubernetes-dev-pod-logs-en` pair improved in every repeat: B6b selected pod
status as support, while B6c selected and hydrated the required pod-list
producer. Across the 87 repeated pairs this yields three improvements, zero
regressions, and 84 ties for producer recall, all-required selection, and
end-to-end structural validity. The mean paired delta was identical in every
repeat, its repeat-level standard deviation was zero, and original-case
outcome consistency was 1.0 for all effectiveness metrics.

Absolute plan-validity rates were not bit-exact across server restarts. Relative
to the earlier single-repeat development artifact,
`mcp-filesystem-dev-edit-file-en` changed from valid to invalid under both B6b
and B6c, reducing both absolute end-to-end rates by `0.0345` without changing
the paired B6c-minus-B6b delta. This is why the causal interpretation relies on
same-run paired conditions rather than comparing absolute rates across runs.

B6c used a mean of 1,452.41 input tokens across selection and planning,
compared with 1,367.24 for B6b. Selection-catalog schema use increased by only
two tokens on average, from 466.62 to 468.62; most of the 85.17-token total
increase occurred after the newly selected producer was hydrated for planning.
This is the expected cost of making the previously excluded dependency
actionable, not a zero-cost quality gain.

The repeated outcome strengthens evidence that the observed mechanism is
stable for this frozen model, prompt, seed policy, and development corpus. It
does not add new independent case families. The clustered confidence intervals
therefore resample 29 original cases after averaging each case's three repeat
deltas; all still include zero. The narrower legacy interval over 87 repeated
rows is retained only for artifact compatibility and is not used for the paper
claim. The held-out split remains sealed and HTTP execution was not performed.
The result is therefore a publication candidate for the narrow
contract-projection mechanism, not evidence of broad statistical superiority.

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
execution and B0-L remain separate experiments. The validated development run
and three-repeat publication candidate support this narrow mechanism claim;
they do not yet support a broad quality or statistical-superiority claim.

The frozen B0-L protocol and runner are documented in
[`paper-llm-catalog-baseline.md`](paper-llm-catalog-baseline.md). It compares
B6c with an exhaustive hierarchical LLM catalog scan under the same per-call
catalog budget while reporting the additional calls, tokens, and latency.
