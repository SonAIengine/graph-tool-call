---
title: "I Built a Graph-Based Tool Search Engine for LLM Agents — Here's What I Learned After 1068 Tools"
published: false
description: "Vector search finds similar tools. Graph search finds the workflow. How graph-tool-call retrieves multi-step tool chains for LLM agents — benchmarked against 6 retrieval strategies across 1068 API endpoints."
tags: ai, python, llm, opensource
canonical_url: https://infoedu.co.kr/ai/agent/graph-tool-call-v015-workflow-chain-competitive-benchmark/
cover_image: https://raw.githubusercontent.com/SonAIengine/graph-tool-call/main/assets/demo.gif
---

## The Problem

LLM agents need tools. But when you have 248 Kubernetes API endpoints or 1068 GitHub API operations, you can't stuff them all into the context window.

The standard fix? Vector search. Embed tool descriptions, find the closest match.

It works for *finding one tool*. But real tasks aren't one tool:

```
User: "Cancel my order and process a refund"

Vector search → cancelOrder (one tool)
What you actually need → listOrders → getOrder → cancelOrder → requestRefund (a chain)
```

Vector search doesn't know `getOrder` must come before `cancelOrder` because it needs the order ID. It doesn't know `requestRefund` follows cancellation. It returns individual matches, not workflows.

I built [graph-tool-call](https://github.com/SonAIengine/graph-tool-call) to solve this. It models tool relationships as a graph and retrieves execution chains, not just individual tools.

After v0.15, I ran a fair competitive benchmark against 6 retrieval strategies. Here's what I found.

## The Uncomfortable Truth: Embedding Wins at Ranking

I compared 6 strategies across 9 datasets (19–1068 tools):

| Strategy | Recall@5 | MRR | Latency |
|---|---|---|---|
| **Vector Only** (like bigtool) | **96.8%** | **0.897** | 176ms |
| BM25 Only | 91.6% | 0.819 | 1.5ms |
| BM25 + Graph | 91.6% | 0.819 | 14ms |
| **Full Pipeline** (BM25+Graph+Embedding) | **96.8%** | **0.897** | 172ms |

**Embedding dominates ranking accuracy.** When you have a good embedding model, Graph and BM25 add zero improvement on top of it.

Worse — Graph was actually *hurting* BM25 results. BM25+Graph scored lower than BM25 alone on several datasets.

## Three Bugs That Made Graph Harmful

### Bug 1: `set_weights()` was silently ignored

```python
# This looks correct but did nothing
tg.set_weights(keyword=1.0, graph=0.0)

# Because _get_adaptive_weights() returned hardcoded values,
# completely ignoring manual settings
def _get_adaptive_weights(self):
    return (0.55, 0.30, 0.0, 0.15)  # ← always this
```

Every benchmark strategy produced identical results. Took 5 benchmark runs to catch this.

### Bug 2: Graph just echoed BM25

The Graph channel started from BM25's top-10 results and expanded their neighbors. It found the same tools BM25already found. Zero independent signal.

### Bug 3: Annotations overwhelmed keyword precision

At 248+ tools, annotation scoring boosted all `create*` tools when it detected "create" intent. This pushed the precise BM25 match (`createCoreV1NamespacedService`) below a wrong match (`createCoreV1Namespace`).

## The Architecture Fix: Graph as Candidate Injection

I removed Graph from the wRRF scoring fusion entirely. Graph now acts as an independent candidate injection channel:

```
Before: BM25 + Graph + Embedding + Annotation → wRRF → results
                ↑ noise

After:  BM25 + Embedding + Annotation → wRRF → primary results
                                                    ↓
        Graph → inject candidates BM25 missed → final results
```

**Key rule: Graph never displaces a BM25 result.** It only adds tools BM25 missed, always below the lowest BM25 score. This guarantees BM25+Graph ≥ BM25 Only.

## Where Graph Actually Wins: Workflow Chains

After the benchmark humbling, I asked: *what can Graph do that embedding can't?*

The answer: **process chains**.

```python
plan = tg.plan_workflow("process a refund")
for step in plan.steps:
    print(f"{step.order}. {step.tool.name} — {step.reason}")
# 1. listOrders — prerequisite for requestRefund
# 2. requestRefund — primary action
```

When an LLM agent gets just `requestRefund`, it calls it, gets "order_id required" error, calls `getOrder`, then retries. **3-4 round trips.**

With the workflow chain: **1 round trip.** The graph knows `REQUIRES` and `PRECEDES` relationships that no amount of embedding can discover.

### Editing Workflows

Auto-generated chains aren't 100% accurate. "close an issue" maps to `updateIssue` but keyword search can't bridge that semantic gap. So I made editing easy:

```python
# Code editing
plan.reorder(["getIssue", "updateIssue"])
plan.set_param_mapping("updateIssue", "issue_id", "getIssue.response.id")
plan.save("close_issue.json")

# Visual editing (opens browser)
plan.open_editor(tools=tg.tools)
```

The visual editor is a zero-dependency single HTML file with drag-and-drop reordering.

## 1068 Tool Stress Test

I threw the entire GitHub REST API (1068 endpoints) at it:

| Strategy | Recall@5 | Miss% |
|---|---|---|
| Vector Only | 88.0% | 12.0% |
| BM25 + Graph | 78.0% | 22.0% |
| Full Pipeline | 88.0% | 12.0% |

Miss cases were all semantic gaps: "Close an issue" → expected `issues/update` (keyword "close" ≠ "update"). This is inherently an embedding problem, not solvable with keywords or graph structure.

## What I Learned

**1. Graph's value isn't retrieval accuracy.** Don't compete with embeddings on ranking individual tools. You'll lose.

**2. Graph's value is structural knowledge.** "What must I call before X?" — only a graph knows this. Embeddings match semantics; graphs encode workflows.

**3. 100% automation isn't the goal.** Auto-generate a good starting point + make editing easy. A visual drag-and-drop editor beats 1% accuracy improvement.

**4. Fair benchmarks are humbling.** My "Graph beats baseline by 70%" story became "Graph ties BM25 at ranking, but uniquely provides workflow chains." Less dramatic, more honest, more useful.

## Try It

```bash
pip install graph-tool-call
```

```python
from graph_tool_call import ToolGraph

tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

# Search
tools = tg.retrieve("place an order", top_k=5)

# Workflow chain
plan = tg.plan_workflow("buy a pet and place an order")
print(plan)  # addPet → placeOrder

# Visual editor
plan.open_editor(tools=tg.tools)
```

Zero dependencies for the core. MIT licensed.

**GitHub**: [github.com/SonAIengine/graph-tool-call](https://github.com/SonAIengine/graph-tool-call)
**PyPI**: [pypi.org/project/graph-tool-call](https://pypi.org/project/graph-tool-call/)
