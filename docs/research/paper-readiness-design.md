# Paper Readiness Research Protocol

> Protocol version: `0.1`
>
> Software baseline: `graph-tool-call 0.34.0` (`7b1e6f4`)
>
> Frozen on: `2026-07-27`
>
> Status: research design. The proposed claims are not paper-ready until the
> exit gates in this document pass.

This document is the canonical protocol for turning graph-tool-call into a
defensible research paper. It separates implemented product capabilities,
candidate scientific contributions, experiments that still need to run, and
claims that may be published only after their evidence is complete.

## 1. Research Position

### 1.1 Working title

> **ContractGraph: Evidence-Carrying Tool Retrieval and Planning over Dynamic
> Heterogeneous API Catalogs**

The final name should be selected only after the related-work review and
artifact release confirm that `ContractGraph` is not already overloaded in the
same research area.

### 1.2 System role

graph-tool-call is a control and data plane between a dynamic tool catalog and
an LLM. Its core retrieval and planning-context construction do not require
model parameter updates, but end-to-end quality still depends on the downstream
model and executor. It is not an LLM training method.

The system:

1. normalizes OpenAPI, GraphQL introspection, MCP-style definitions, Python
   functions, and generic tool catalogs into executable tool contracts;
2. derives semantic, IO-contract, provenance, and graph evidence;
3. retrieves a bounded candidate subgraph for a natural-language request;
4. selects a target and expands required producer tools;
5. exposes evidence and readiness diagnostics to any compatible LLM or
   executor; and
6. optionally converts scrubbed execution traces into collection-local,
   gated ranking evidence.

The current paper must not claim model fine-tuning, learned reasoning, or
parameter improvement. Model training is a possible follow-up workstream after
the middleware and its benchmark are independently established.

In this protocol, `model-agnostic` means that the core accepts and returns
structured contracts without depending on one model vendor or learned model
weights. It does not mean that every downstream LLM will use the same candidate
set equally well.

### 1.3 Candidate thesis

> Executable contracts and typed dependency evidence extracted from
> heterogeneous tool descriptions can reduce the tool context exposed to an
> LLM while preserving retrieval, target selection, and multi-step execution
> quality on dynamic and previously unseen catalogs.

This thesis is falsifiable. The paper fails if a competitive flat hybrid
retriever achieves equivalent quality and efficiency, if contract/graph
ablations show no meaningful contribution, or if gains disappear on unseen
catalogs.

### 1.4 System boundary

In scope:

- source detection and normalization;
- contract extraction and schema preservation;
- deterministic semantic annotation;
- graph construction and evidence merging;
- retrieval, target selection, producer expansion, and plan readiness;
- optional collection-local trace evidence;
- benchmark artifacts, diagnostics, and reproducibility.

Out of scope:

- LLM pretraining, SFT, RL, or reasoning-trace optimization;
- XGEN database, session, auth-profile, SSE, and UI implementation;
- automatic execution of unsafe write operations;
- claims that a local BFCL-compatible run is an official BFCL leaderboard
  submission.

## 2. Novelty Hypothesis and Related Work

The contribution cannot be "we use a graph for tools." Dependency graphs,
learned graph retrieval, trajectory graphs, and experience memory already
exist. The defensible contribution must be the complete combination of
heterogeneous executable contract normalization, evidence-carrying graph
retrieval, planning readiness, and dynamic-catalog evaluation without model
parameter updates.

| Work | Primary focus | Difference to test, not assume |
|---|---|---|
| ToolLLM | Large tool-use dataset and tool-use model | graph-tool-call does not train the LLM; it controls the candidate contract surface |
| RAG-MCP | Retrieval over MCP tool descriptions | test whether typed contract and dependency evidence adds value over flat retrieval |
| Tool Graph Retriever | Learned dependency-aware graph retrieval | compare against graph topology alone and clearly separate deterministic contract extraction from learned graph representations |
| SkillGraph | Execution-transition graph mined from trajectories | graph-tool-call starts from executable contracts and treats trace evidence as optional, gated evidence rather than the primary graph |
| ExpGraph | Graph-structured experience memory | test cold-start quality before any execution history and incremental value after trace promotion |
| HyFunc | Efficient dynamic function retrieval/calling | compare candidate quality and end-to-end efficiency under unseen tool catalogs |
| BFCL V4 | Function-calling and agentic evaluation | use its official task/evaluation semantics where possible; label local-compatible runs accurately |
| MCP-Atlas | Real MCP-server benchmark | candidate external benchmark for heterogeneous, multi-step tool use, subject to license and harness audit |
| Toolathlon | Long-horizon, execution-verified multi-app tasks | candidate external stress test, not a replacement for contract-level evaluation |
| GLM-5 | Tool-use and reasoning training recipe | future model-training direction; not a baseline for the current middleware claim |

Primary references are maintained in [`references.md`](references.md). Before
submission, each matrix row needs a full paper read, implementation audit when
code is available, and a precise capability-by-capability comparison. Abstract
comparison alone is insufficient for a novelty claim.

### 2.1 Terms that must remain distinct

An **executable contract** is more than searchable documentation. It is the
minimum normalized information needed to validate and construct a call:

```text
identity + input locations/types/requiredness + output shape/types
+ auth declaration + execution template + source provenance
```

Evidence is divided into four non-interchangeable classes:

| Evidence class | Meaning | Example |
|---|---|---|
| contract evidence | typed compatibility between inputs and outputs | response `orderId` can satisfy required path `orderId` |
| semantic evidence | query-to-tool meaning alignment | action=`read`, resource=`order`, shape=`single` |
| provenance evidence | origin and derivation of a fact | OpenAPI response schema, manual edge, run-observed edge |
| outcome evidence | observed execution result after scrubbing | repeated successful target or plan path |

An evidence-carrying result must identify its evidence class, source, score or
confidence, and affected candidate. A numeric BM25 score alone is a ranking
signal, not contract evidence.

### 2.2 Capability matrix to complete before submission

`?` means the cited implementation or artifact still needs verification. The
paper cannot turn a `?` into a negative claim based only on an abstract.

| Capability | graph-tool-call candidate | Flat RAG-MCP | Tool Graph Retriever | SkillGraph | ExpGraph |
|---|:---:|:---:|:---:|:---:|:---:|
| heterogeneous source normalization | yes | ? | ? | ? | ? |
| executable request and response preservation | yes | ? | ? | ? | ? |
| typed producer/consumer data flow | yes | no/verify | ? | transition-derived | experience-derived |
| useful before execution history | yes | yes | yes | verify | verify |
| evidence source exposed per candidate | yes | ? | ? | ? | ? |
| target and producer candidates separated | yes | ? | ? | ? | ? |
| no learned retriever required | yes | yes | no | verify | verify |
| dynamic unseen-catalog evaluation | planned | ? | ? | ? | ? |

The related-work audit must replace every `?` with a cited fact and add the
closest reproducible method to the baseline harness. If that method cannot be
run, the paper reports the limitation and narrows its comparison claim.

## 3. Formal Problem

Let a catalog be:

```text
C = {c_1, ..., c_n}
```

Each normalized tool contract contains:

```text
c_i = (identity, semantics, input_schema, output_schema, auth,
       execution_template, provenance)
```

The system derives an evidence graph:

```text
G = (C, E)
```

where an edge has a typed relation, confidence, evidence source, and optional
data-flow mapping. Given user query `q` and context `x`, retrieval returns a
bounded candidate subgraph:

```text
S_k = R(q, x, C, G, B)
```

where `B` is a tool/token budget. Target selection chooses `t` from `S_k`, and
producer expansion constructs a candidate plan:

```text
P = (p_1, ..., p_m, t)
```

The evaluation jointly measures:

- whether expected target and producer tools are preserved;
- whether required inputs can be resolved;
- whether an LLM emits a valid call or plan;
- whether execution reaches the expected state;
- context size, build/search latency, and model calls; and
- whether all decisions retain auditable evidence.

Primary optimization is not retrieval accuracy alone:

```text
maximize  execution_quality(S_k, P)
minimize  context_tokens(S_k), latency(R), unsafe_failures
subject to contract_preservation and evidence_traceability
```

## 4. Research Questions

### RQ1. Contract normalization

How accurately can one model-independent normalization layer preserve executable
request, response, auth, and provenance contracts across heterogeneous source
types?

### RQ2. Retrieval and selection

Does contract-aware graph retrieval improve target and producer recall over
lexical, dense, hybrid, and flat-metadata retrieval at the same candidate
budget?

### RQ3. Planning and execution

Does typed IO evidence improve plan validity, required-field resolution, and
execution success for multi-step requests?

### RQ4. Scale and efficiency

How does quality change as catalog size and context budget grow, and how much
actual tokenizer context and latency does the candidate subgraph save?

### RQ5. Generalization

Do improvements hold for unseen API families, source types, domains,
languages, and LLMs without source-specific rules?

### RQ6. Trace evidence

After cold-start evaluation is fixed, does promoted execution evidence improve
future ranking or plan selection without increasing regressions or leaking
sensitive data?

RQ6 is secondary. It must not obscure the cold-start contribution and may move
to an appendix or follow-up paper if public reproducible traces are
insufficient.

## 5. Preregistered Hypotheses

Thresholds below are proposed submission gates, not current results.

| ID | Hypothesis | Primary measure | Proposed minimum effect |
|---|---|---|---:|
| H1 | Contract + graph outperforms the strongest flat retriever at equal budget | workflow Recall@5 | `+3` absolute points and 95% CI excludes `0`; smaller gains are not practically sufficient |
| H2 | IO-contract edges improve producer discovery | producer Recall@5 | `+5` absolute points over graph-without-contract |
| H3 | The full pipeline is non-inferior to full-catalog model quality while using less context | paired E2E non-inferiority and token reduction | lower CI above `-2` points; tokens reduced `>= 80%` |
| H4 | Gains survive unseen catalog families | unseen-family workflow Recall@5 | `+3` points over strongest flat baseline |
| H5 | Normalization remains executable across source types | required contract preservation | macro average `>= 0.95` |
| H6 | Promoted trace evidence helps without broad regressions | paired E2E success | positive delta; per-case cold-to-adaptive regression rate `<= 1%` |

For each hypothesis, the exact primary metric, dataset subset, model revision,
candidate budget, and statistical test must be frozen before the final run.
Thresholds may change during pilot experiments only if the change and reason
are recorded before test-set evaluation.

## 6. Candidate Contributions

The paper may claim the following only when its corresponding experiment
passes:

1. **Heterogeneous executable contract graph.** A common representation that
   retains callable request/response schemas, auth requirements, semantic
   metadata, provenance, and typed data-flow evidence across supported source
   types.
2. **Evidence-carrying candidate construction.** A retrieval-to-plan pipeline
   that separates target candidates from producer expansion and makes each
   ranking or graph signal inspectable.
3. **Dynamic-catalog evaluation protocol.** Frozen unseen-family and unseen-
   source splits that prevent operation aliases from crossing train/dev/test.
4. **Context-quality trade-off.** Evidence that bounded candidate subgraphs
   preserve model and execution quality while reducing actual tokenizer
   context.
5. **Large-catalog deployment case study.** An aggregate case study over a
   thousand-tool catalog at one organization, without exposing private specs or
   treating private cases as the sole evidence.

Trace learning is not a required main contribution. It becomes one only if a
public trace corpus, safety audit, and statistically significant evaluation
are available.

## 7. Evaluation Datasets

### 7.1 Public core

The main paper must be reproducible without XGEN credentials.

| Suite | Purpose | Required status before use |
|---|---|---|
| BFCL V4 non-live subsets | standard target/call generation and multi-tool comparison | official data/evaluator version frozen; local deviations documented |
| Existing graph-tool-call eight-suite benchmark | deterministic retrieval and regression continuity | ground truth audited; stale v0.12 result tables regenerated |
| Public OpenAPI suite | REST contract preservation and unseen-family evaluation | immutable specs, licenses, hashes, and case annotations published |
| Public GraphQL introspection suite | non-REST normalization and execution | endpoint snapshots, schema hashes, and deterministic read cases published |
| Public MCP/tool-catalog suite | protocol-neutral heterogeneous retrieval | tool definitions and expected workflows published |
| MCP-Atlas public subset | external real-server validation | license, container harness, and result comparability audited |
| Toolathlon subset | optional long-horizon stress test | reproducible executor and cost budget available |

MCP-Atlas and Toolathlon are candidate external suites. They are not mandatory
until their public artifacts and licenses are verified.

### 7.2 Industrial external validation

The X2BEE/XGEN snapshot is a separate external-validity section:

- no private operation names or schemas in the public artifact;
- publish only aggregate catalog and quality statistics approved for release;
- freeze source manifest hashes, software revision, and case IDs internally;
- do not tune on held-out XGEN cases after observing their final result;
- report private-case limitations prominently.

Current historical evidence includes a 1,084-tool collection and major context
reduction, but those figures must be rerun on the frozen paper revision and
must not substitute for public experiments.

### 7.3 Split policy

Every case receives these labels:

```text
source_type: openapi | graphql | mcp | python | catalog
domain: commerce | developer | infrastructure | productivity | ...
catalog_size: <50 | 50-250 | 251-1000 | >1000
language: en | ko | mixed
workflow_length: 1 | 2 | 3+
contract_shape: flat | nested | array | envelope | polymorphic
auth: none | declared | runtime-required
mutation: read | write
```

Required splits:

- random in-distribution split for continuity only;
- unseen API-family/spec split;
- unseen domain split;
- unseen source-type transfer when enough source types are available;
- temporal holdout where a trustworthy source publication date is available;
- Korean, English, and mixed-language slices;
- catalog-size and workflow-length slices.

Leakage controls:

- split by API family and immutable spec hash, not by individual query;
- aliases or versions of the same operation remain in one split;
- synthetic paraphrases of one seed remain in one split;
- benchmark-specific rules cannot inspect expected tool IDs;
- tuning uses train/dev only; test artifacts are generated once per release
  candidate;
- all exclusion and deduplication decisions are recorded.

Model contamination cannot be ruled out for proprietary training corpora.
Instead, the evaluation includes a contamination-sensitivity protocol:

- exact and near-duplicate checks between benchmark descriptions and any known
  model training/evaluation corpus available to the authors;
- a temporal API holdout newer than the documented model cutoff when dates are
  trustworthy;
- locally generated but independently annotated schemas whose names and
  descriptions were not published before evaluation;
- renamed-identifier and paraphrased-description robustness slices;
- separate reporting for popular public APIs and newly constructed catalogs.

These tests reduce memorization risk but do not prove the absence of model
training contamination. The limitation must remain explicit.

### 7.4 Annotation protocol

Each public case contains:

```json
{
  "case_id": "stable-id",
  "query": "natural language request",
  "expected_targets": ["tool-a"],
  "required_producers": ["tool-b"],
  "acceptable_alternatives": [],
  "expected_result_shape": "single",
  "required_fields": ["resource_id"],
  "workflow_constraints": [],
  "execution_assertions": [],
  "provenance": {
    "spec_sha256": "...",
    "annotator_version": "..."
  }
}
```

At least two annotators independently label the test subset. Disagreements are
adjudicated and inter-annotator agreement is reported for target, producer,
and workflow labels. Cases with multiple valid plans must encode equivalence
instead of forcing one arbitrary sequence.

For a stratified sample of at least 100 queries, annotators also rate the
top-K candidate relevance on a three-level scale: required, useful alternative,
or irrelevant. This supports graded nDCG, tests ground-truth completeness, and
reports Krippendorff's alpha or Cohen's kappa as appropriate. Korean and English
annotations use bilingual review rather than automatic translation alone.

## 8. Baselines

All retrieval baselines receive the same normalized text and the same
candidate budget unless the experiment explicitly isolates normalization.
The deterministic development harness preserves its original candidate-count
view and also emits a paired actual-token view under one frozen tokenizer,
serialization, and whole-schema truncation policy; see
[`paper-baselines.md`](paper-baselines.md).

| ID | Baseline |
|---|---|
| B-1 | Seeded random candidates at the same K; publication runs also enforce token budget |
| B0 | Full catalog to the model, subject to context limit |
| B0-O | Oracle target/producer candidate set, measuring the post-retrieval ceiling |
| B0-L | LLM catalog selector over the full or hierarchically chunked catalog |
| B1 | Fixed BM25 over name, summary, and description |
| B2 | Dense embedding retrieval with a frozen public embedding model |
| B3 | BM25 + dense using unweighted RRF with `k=60` |
| B4 | B3 over flat action/resource/module/result-shape metadata, no edges |
| B5 | B4 + untyped graph topology, no IO-contract fields |
| B6 | Graph + typed IO contract, no target selector |
| B6a | B6 + opt-in required-consumer-aligned output promotion |
| B6b | B6a + one evidence-gated consumer-aligned candidate slot |
| B6c | B6b ranking + selection-time contract projection for evidence-admitted candidates |
| B7 | Full graph-tool-call pipeline: retrieval + selector + producer expansion |
| B8 | Closest reproducible published graph retriever |
| B9 | Optional external or small reranker over the same candidate pool |

The primary flat comparator is the strongest frozen B1-B4 method on development
data, selected before the held-out split is opened. Development selection must
be recorded as a protocol decision; fusion weights may not be tuned on the test
split. B0-L receives an explicit context/chunking budget and reports model
calls, tokens, latency, and cost so that it is not an unbounded baseline.

The related-work audit names B8 before test evaluation. If an exact reproduction
is impossible, report the missing artifact and avoid superiority claims
against that method.

Model-in-loop comparisons use:

- at least one strong hosted or reproducibly served model;
- at least one smaller open-weight model;
- identical system prompts, tool schemas, decoding settings, and retry policy;
- full catalog versus each retrieval method where the context window permits.

Model choice is frozen by exact provider/model revision and chat template, not
by a floating product alias.

## 9. Ablation Matrix

The main ablation table uses one frozen implementation and toggles one
component at a time:

| Ablation | Question |
|---|---|
| no deterministic semantic metadata | Do action/resource/module signals matter? |
| no graph expansion | Does graph structure add value over flat retrieval? |
| no IO contract | Are typed request/response dependencies useful? |
| no consumer-aligned output promotion | Do required consumers recover useful response paths without unacceptable graph growth? |
| no producer expansion | Is multi-step coverage coming from explicit producer discovery? |
| no target selector | Does guarded selection reduce sibling ambiguity? |
| no result-shape signal | Does single/list/count/mutation disambiguation matter? |
| structural edges only | How much comes from name/manual/run evidence? |
| no promoted trace evidence | Does usage evidence help after cold start? |
| fixed Top-K sweep | What is the quality/context Pareto frontier? |
| fixed token-budget sweep | Does the method remain useful under real context limits? |

Do not combine multiple new heuristics into one unnamed "full" delta. Each
material component must have a single-component ablation or be excluded from
the contribution claim.

## 10. Metrics

### 10.1 Ingestion and contract fidelity

- operation retention and duplicate-resolution rate;
- request/response schema coverage;
- required field, location, enum, content type, and auth preservation;
- nested object/array and response-envelope leaf alignment;
- execution-template completeness;
- source detection accuracy and unsupported-source diagnostics;
- macro average across source types, not only operation-weighted micro average.

### 10.2 Retrieval and candidate construction

- Recall@K, all-required-tools Recall@K, Hit@K;
- Precision@K, F1@K, MRR, MAP, and nDCG;
- target recall and producer recall separately;
- workflow coverage;
- candidate count and candidate-token budget;
- rank compression: expected tools found by depth but missing at K;
- evidence-source attribution and missing-evidence taxonomy.

### 10.3 Target, plan, and execution

- target exact/equivalent accuracy;
- selector override precision, recall, and regression rate;
- tool-sequence exact match and set F1;
- dependency order validity;
- required-field resolution and binding accuracy;
- strict/equivalent function-call accuracy;
- execution assertion success;
- recovery success after structured failure;
- failures by retrieval, selection, plan, auth, binding, HTTP, and assertion
  stage.

Every failed case receives one primary failure code:

| Code | Operational definition |
|---|---|
| `contract_loss` | required callable information was lost during normalization |
| `retrieval_miss` | an expected target is absent at the evaluated K |
| `producer_miss` | target is present but a required producer is absent |
| `candidate_ambiguity` | expected tool is present but selector/model chooses a sibling |
| `argument_mismatch` | selected tool is valid but required arguments are wrong or missing |
| `dependency_order_error` | valid tools are called in an invalid order |
| `auth_readiness_failure` | execution is blocked before API call by missing auth context |
| `execution_failure` | a syntactically valid call fails at the tool/API layer |
| `assertion_failure` | calls complete but expected final state/result is not reached |

Secondary codes may add detail, but one deterministic precedence rule assigns
the primary code. Two reviewers audit a stratified failure sample.

### 10.4 Efficiency

- actual tokenizer input tokens, not character count alone;
- context reduction against full-catalog and strongest flat baseline;
- graph build time and peak memory;
- retrieval, selection, and plan-context p50/p95 latency;
- model calls, model latency, and monetary cost per query;
- quality versus token/latency Pareto frontier.

### 10.5 Safety and auditability

- raw secret or personal-data persistence count must be zero;
- unsafe mutation execution count;
- auth readiness false-pass rate;
- proportion of selected targets with complete evidence;
- deterministic replay agreement for the same artifact and seed.

## 11. Statistical Protocol

- Freeze all seeds, model settings, prompts, templates, and test cases before
  final runs.
- Run deterministic retrieval once after proving byte-for-byte replay
  stability.
- Run stochastic model experiments at least three times per condition.
- Report per-case paired bootstrap 95% confidence intervals.
- Use McNemar's test for paired binary success outcomes.
- Use a paired permutation test or Wilcoxon signed-rank test for rank, token,
  and latency differences when distribution assumptions are weak.
- Report effect sizes and raw deltas, not p-values alone.
- Correct families of secondary comparisons with Holm's method.
- Publish macro averages and important slices; do not hide regressions behind
  operation-weighted micro averages.
- Select one primary endpoint per research question before the final test run.

Before freezing the test set, run a prospective power analysis for every
primary hypothesis. For H1, use a paired binary formulation at the case level,
two-sided `alpha=0.05`, power `>= 0.80`, the proposed three-point effect, and
the train/dev estimate of discordant pairs. Record the assumed discordance and
required sample size. As an illustration, a three-point paired difference can
require roughly 900 cases when discordance is around 10%, and substantially
more when discordance is higher; `1000` is not automatically sufficient.

Primary comparisons are H1 B7-vs-strongest-flat, H2 B6-vs-B5, H3 B7-vs-B0, and
H5 normalized-vs-source contract. All other baseline, slice, and ablation
comparisons are secondary and form the Holm-corrected family. Equivalence-aware
success is computed before statistical testing, so multiple valid targets or
plans do not become artificial ties.

The existing paired t-test can remain as a compatibility output, but it is not
the sole statistical evidence for bounded or binary metrics.

## 12. Experiment Stages

### P0. Safety and artifact preflight

Before any experiment, validate licenses, manifests, secret scrubbing, and
artifact output paths. This is a prerequisite, not research evidence.

Exit criterion:

- all public inputs have licenses and hashes;
- no secret is present in artifacts.

### E0. Adapter conformance

Validate normalized contracts, execution templates, source diagnostics, and
deterministic replay. No LLM is required.

The deterministic runner and metric contract are implemented in
[`adapter-conformance.md`](adapter-conformance.md). The current train/dev pilot
passes, but E0 is not a publication claim until the held-out and clean-machine
gates are completed.

Exit criterion:

- the complete run can be reconstructed in a clean environment;
- macro contract-fidelity metrics are available by source type;
- every unsupported source fails with a structured diagnostic.

### E1. Cold-start deterministic retrieval

Run B-1 through B8 on all public datasets and frozen splits. Produce Top-K and
token-budget sweeps plus failure bundles.

Exit criterion:

- H1/H2 pilot effect is visible on train/dev;
- no test split has been inspected;
- all ablation and baseline commands are automated.

### E2. Model-in-loop function calling

Run full-catalog and retrieved candidates with frozen model revisions. Use the
official BFCL evaluator where its data applies and a separately named
graph-tool-call evaluator for additional datasets.

Exit criterion:

- at least two model scales;
- at least three repeats;
- strict and equivalence-adjusted results with confidence intervals.

### E3. Multi-step public execution

Execute read-only or isolated-fixture workflows with target, producer,
argument, ordering, and final-state assertions.

Exit criterion:

- execution environment is containerized or otherwise reproducible;
- write cases have reset/cleanup;
- uncaught runner errors are zero.

### E4. Trace evidence

Freeze cold-start results, then apply only scrubbed and promoted train-history
suggestions. Test on later or held-out query families.

This experiment is disabled in every main cold-start table. It is reported as
an adaptive evidence study, not LLM learning. By default it belongs in the
appendix; it moves into the main paper only if a public temporal trace split is
releasable.

Exit criterion:

- no test outcome is used to promote its own suggestion;
- H6 safety and regression gates pass;
- cold-start results remain separately reported.

### E5. XGEN large-catalog validation

Replay a frozen private snapshot and Quality Lab suite. Report aggregate
quality, context, latency, and failure taxonomy.

Exit criterion:

- primary public claims and configurations are frozen before this run;
- private data handling is approved;
- no product-specific rule exists in library scoring.

## 13. Claim-Evidence Ledger

Every sentence in the abstract and conclusion must map to a frozen artifact.

| Claim candidate | Required evidence | Current status |
|---|---|---|
| heterogeneous executable normalization | public conformance corpus for each supported adapter | blocked |
| contract graph improves retrieval | B1-B7 plus B8 when reproducible, paired on unseen families | blocked |
| producer expansion improves planning | multi-step public plan and execution suite | blocked |
| large context reduction with preserved quality | actual tokenizer counts plus model E2E | partial; historical char/tool proxies only |
| model-portable behavior | at least two frozen model families | blocked |
| one-organization large-catalog applicability | frozen XGEN aggregate replay | partial; historical 0.28 evidence |
| trace evidence improves future use | leakage-safe temporal/public trace experiment | blocked |

Artifact metadata must include:

```text
paper_protocol_version
graph_tool_call_version
git_commit
dataset_manifest_sha256
case_split_sha256
model_provider/model_revision
chat_template_sha256
prompt_sha256
tokenizer_revision
dependency_lock_sha256
seed
hardware
started_at/finished_at
command
```

## 14. Reproducibility Package

The paper artifact repository or release bundle must contain:

- dataset download/snapshot scripts and license inventory;
- immutable manifests and split files;
- normalized contracts or deterministic builders;
- all baseline and ablation configurations;
- model prompts and tool serialization templates;
- exact commands for every table and figure;
- raw per-case results with sensitive values removed;
- statistical analysis scripts;
- environment lock, hardware notes, and expected runtime/cost;
- a digest-pinned container image and CPU-only deterministic reference run;
- a one-command deterministic smoke and a documented full-run pipeline;
- a claim-to-table-to-artifact index.

Private XGEN artifacts remain outside the public bundle, but an aggregate
schema and a released synthetic scale twin must demonstrate how the same
evaluator is used. The twin matches only non-sensitive aggregate properties:
catalog size distribution, schema depth, source count, edge density, duplicate
rate, required-field rate, and workflow length.

Before submission, complete the target venue's reproducibility checklist and
map every checklist item to the artifact or manuscript section. Reproduction
must be attempted from a fresh checkout by someone who did not implement the
experiment harness.

## 15. Threats and Limitations

- **Benchmark leakage:** popular API descriptions may occur in model training
  data. Contamination-sensitivity and temporal splits reduce, but cannot remove,
  this uncertainty. The study tests system generalization, not model novelty.
- **Synthetic query bias:** generated paraphrases can overstate coverage.
  Human-authored and execution-derived cases must be reported separately.
- **Private external validation:** XGEN scale supports realism but limits
  reproducibility.
- **Model nondeterminism:** provider revisions and stochastic decoding can
  change results; exact revisions and repeats are required.
- **Source coverage:** GraphQL subscriptions, gRPC reflection, event streams,
  browser-discovered traffic, and undocumented protocols are not all supported
  by the 0.34 baseline.
- **Runtime auth:** a valid contract does not guarantee that credentials or
  business preconditions are available.
- **Graph quality:** structural or name-based edges can be dense and misleading;
  evidence-source ablations and visual-edge filtering are necessary.
- **Equivalent plans:** multiple valid call sequences make exact sequence
  accuracy an incomplete metric.
- **No model learning claim:** improved candidate evidence may help an LLM
  without changing its underlying reasoning ability.

## 16. Submission Gates

### Main-paper gate

Do not submit a full paper claiming general effectiveness until all are true:

- a public heterogeneous benchmark with immutable licenses, hashes, and splits;
- unseen-family and unseen-domain evaluation;
- B-1 through B8 baselines or a documented inability to reproduce B8, plus
  component ablations;
- actual tokenizer context and end-to-end execution metrics;
- at least two model families and three repeats with confidence intervals;
- official BFCL evaluation semantics used or every deviation named;
- public multi-step execution cases;
- regenerated broad BFCL run on the paper revision;
- no unresolved secret/privacy finding;
- public reproducibility package passes in a clean environment;
- the claim-evidence ledger has no blocked primary claim.

### Workshop or technical-report gate

A narrower paper may proceed when:

- one public source type plus one held-out source type are complete;
- deterministic retrieval and model-in-loop results have paired baselines;
- at least one multi-step public executor is reproducible;
- the title and claims explicitly limit source, scale, and model scope;
- incomplete deployment and adaptive-evidence results are labeled preliminary.

The workshop path must not publish paper-ready language for untested generality.

## 17. Work Packages

| WP | Deliverable | Exit criterion |
|---|---|---|
| WP0 Protocol freeze | reviewed RQs, claims, splits, and metrics | protocol tag and decision log |
| WP1 Public corpus | OpenAPI + GraphQL + MCP manifests and annotations | license/hash/annotation audit passes |
| WP2 Unified harness | B-1 through B8 and per-stage metrics in one artifact schema | clean deterministic replay |
| WP3 Ablations | all component and budget sweeps | paired tables with CI |
| WP4 Model and execution | two-model BFCL plus public multi-step E2E | repeats, official semantics, no uncaught errors |
| WP5 Deployment validation | frozen XGEN aggregate report | private-data review and no product rule |
| WP6 Artifact release | scripts, locks, results, statistics | independent clean-machine reproduction |
| WP7 Manuscript | paper, appendix, model/data cards | every primary claim linked to evidence |

Recommended implementation order:

1. freeze the public dataset manifest and split policy;
2. replace scattered benchmark result schemas with one experiment artifact;
3. implement missing random/oracle/LLM/flat/dense/hybrid baselines before new
   heuristics;
4. add actual tokenizer accounting and adapter conformance metrics (implemented
   for train/dev; held-out evaluation remains frozen);
5. run deterministic ablations;
6. run small model subsets, then expensive full model evaluations;
7. perform XGEN external validation last.

This order prevents five-hour model runs from becoming the development loop.

## 18. Manuscript Outline

1. **Introduction:** dynamic tool catalogs, context limits, and executable
   dependency problem.
2. **Related Work:** tool retrieval, dependency graphs, experience memory,
   function-calling benchmarks, and tool-use training.
3. **Problem and System:** normalized contracts, evidence graph, retrieval,
   target selection, producer expansion, and trace boundary.
4. **Heterogeneous Tool Benchmark:** sources, annotation, splits, leakage
   controls, and evaluator.
5. **Experiments:** cold-start retrieval, ablations, scale/context trade-off,
   model-in-loop, and multi-step execution.
6. **Deployment Case Study:** aggregate XGEN results and operational lessons.
7. **Trace Evidence Study:** optional secondary experiment.
8. **Limitations and Ethics:** privacy, auth, mutations, private data, and
   model contamination.
9. **Conclusion.**

## 19. Decision Log

| Date | Decision |
|---|---|
| 2026-07-27 | The first paper studies model-independent retrieval middleware, not LLM training. |
| 2026-07-27 | Cold-start contract/graph quality is primary; adaptive trace evidence is appendix/follow-up by default. |
| 2026-07-27 | XGEN is external validation, not the only or primary dataset. |
| 2026-07-27 | Local BFCL-compatible results are not called official leaderboard results. |
| 2026-07-27 | Actual tokenizer tokens replace tool-count/character proxies in primary efficiency claims. |
| 2026-07-27 | Main-paper claims require public heterogeneous and unseen-family evaluation. |
| 2026-07-28 | AI-assisted annotation review may unblock development but never substitutes for independent human review. |
| 2026-07-28 | Experiment schema v1 separates deterministic run identity from exact result content identity. |
| 2026-07-29 | The strongest frozen B1-B4 development result becomes the primary flat comparator; B3 remains reported even when fusion underperforms B2. |
| 2026-07-30 | B5-B7 share B4 seeds and budgets; graph, typed-contract, and selector/producer effects are reported as paired deltas. |
| 2026-07-30 | Producer-edge failures are diagnosed with ground-truth-only contract, path, direction, and seed coverage before graph weights are tuned. |
| 2026-07-30 | Required-consumer-aligned output promotion improves contract-path coverage but not Recall@5 under protected B4 seeds; candidate admission is the next isolated ablation. |
| 2026-07-30 | B6c selection-time contract projection preserves B6b ranking and restores its producer gain under 2,048 tokens; complete schemas remain mandatory before argument generation and execution. |

## 20. Immediate Next Tasks

- [ ] Audit licenses and reproducibility of BFCL V4, MCP-Atlas, and Toolathlon.
- [x] Define and hash the first public OpenAPI/GraphQL/MCP seed corpus manifest.
      See [`public-heterogeneous-corpus.md`](public-heterogeneous-corpus.md).
- [x] Upgrade public-corpus ground truth from a flat tool list to
      target/producer/alternative annotations.
- [x] Add adapter conformance metrics for request, response, auth, execution
      templates, IO contracts, deterministic replay, and unsupported
      diagnostics. See [`adapter-conformance.md`](adapter-conformance.md).
- [x] Implement B2 dense and B3 fixed hybrid baselines in the unified harness.
- [x] Add seeded random and oracle baselines to the unified harness.
- [x] Add the fixed B1 BM25 baseline to the unified harness.
- [x] Add the fixed B4 flat-semantic hybrid baseline to the unified harness.
- [x] Add frozen B5 untyped graph, B6 typed-contract graph, and B7 full
      deterministic pipeline baselines with paired bootstrap deltas.
- [x] Add producer-target contract, edge, path, and seed coverage diagnostics
      that are recorded but never used for ranking.
- [x] Add the B6a required-consumer-aligned output-promotion ablation and
      record both structural coverage gains and graph-growth cost.
- [x] Add a frozen candidate-admission/seed-slot ablation without changing
      retrieval channels, graph weights, or output-promotion policy. B6b
      improves candidate-count producer recall without an effectiveness
      regression, but the gain does not survive the 2,048-token whole-schema
      budget; see [`paper-baselines.md`](paper-baselines.md).
- [x] Add a budget-aware contract-projected schema ablation that preserves
      B6b's producer under the same 2,048-token limit. B6c raises token-budget
      producer recall from `0.5000` to `0.6667` on train/dev with one improved
      case and no observed effectiveness regression; the confidence interval
      includes zero, so model-in-loop and broader-corpus validation remain
      open. See [`paper-baselines.md`](paper-baselines.md).
- [ ] Run a frozen model-in-loop B6b-vs-B6c target-selection comparison, then
      hydrate the selected tool's complete schema before argument generation.
      The paired two-pass harness and artifact contract are implemented; the
      clean fixed-model run remains. See
      [`paper-model-loop.md`](paper-model-loop.md).
- [ ] Add the budgeted LLM catalog-selector baseline.
- [x] Add actual tokenizer accounting with frozen tokenizer revisions.
      The B-1/B0-O/B1-B7 harness uses pinned Qwen3 tokenizer accounting and a
      ranked whole-schema prefix policy; see
      [`paper-baselines.md`](paper-baselines.md).
- [x] Define one artifact schema for deterministic, model, execution, and XGEN
      runs. See [`experiment-artifact.md`](experiment-artifact.md).
- [x] Freeze public-corpus train/dev/test family splits before tuning new
      retrieval rules.
- [ ] Complete contamination-sensitivity and prospective power analyses.
- [ ] Run the full ablation matrix on train/dev.
- [ ] Review the protocol with one independent researcher before opening the
      held-out test split.
