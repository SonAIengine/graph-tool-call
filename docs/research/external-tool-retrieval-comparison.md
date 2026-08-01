# External Tool-Retrieval Comparison

## Why this track exists

The public heterogeneous corpus measures graph-tool-call against frozen internal
ablations. It does not establish relative standing against published tool-retrieval
systems. This track adds two-way external validation:

1. run comparable external methods on graph-tool-call's public corpus; and
2. run graph-tool-call on the external method's official dataset.

Scores are comparable only when the dataset, candidate catalog, embedding model,
top-K, query text, and metric implementation are held constant.

## Comparison set

| System | Primary mechanism | Fair comparison role | Status |
|---|---|---|---|
| ToolRet | 43K-tool retrieval benchmark and trained retrievers | Large-catalog retrieval track | Adapter next |
| Re-Invoke | Synthetic multi-view tool descriptions and query rewriting | Training-free retrieval baseline | Method adapter next |
| ToolRerank | Adaptive truncation and hierarchy-aware reranking | Reranking baseline | Repository currently empty; paper protocol required |
| Graph RAG-Tool Fusion | Vector seeds followed by dependency DFS | Closest graph traversal baseline | ToolLinkOS parity implemented |
| TGR | Learned dependency discriminator and graph convolution | Learned graph baseline | Reproduction audit next |
| LangGraph Bigtool | Semantic search and just-in-time tool loading | Practical dense-retrieval baseline | Equivalent dense baseline available |
| Anthropic Tool Search | Regex/BM25 with deferred tool definitions | Product lexical baseline | Equivalent BM25 baseline available |

Equivalent means that the retrieval mechanism can be represented under the same
frozen input fields. It does not mean proprietary product scores have been
reproduced.

## ToolLinkOS parity protocol

ToolLinkOS is the first external track because its official repository publishes:

- 573 tools;
- 1,569 queries;
- the main target and complete required dependency set for every query; and
- a manual dependency graph.

The dataset is downloaded from commit
`b630b98656e25c3b83a71ea0406572add38ae46d` under its MIT license.

```bash
poetry install --with dev -E embedding-local
make paper-toolinkos-parity

poetry run python -m benchmarks.experiment.cli validate \
  /tmp/graph-tool-call-toolinkos-parity.json
```

The paired run evaluates:

- frozen BM25;
- revision-pinned multilingual E5 dense retrieval;
- unweighted BM25+dense RRF;
- Graph RAG-Tool Fusion Algorithm 1 using hybrid top-3 seeds and dependency DFS;
- graph-tool-call's frozen typed/confidence-weighted graph traversal.

Metrics are mAP, recall, nDCG, target hit, all-required coverage, and latency at
K=10, 20, and 30.

### Interpretation boundary

This track supplies both systems with ToolLinkOS's manual dependency graph. It
tests retrieval and traversal quality given a graph. It does **not** test
graph-tool-call's automatic OpenAPI/MCP/GraphQL contract extraction or graph
construction.

The paper's reported ToolLinkOS reference values are BM25 `0.185`, naive RAG
`0.210`, hybrid RAG `0.202`, Graph RAG-Tool Fusion `0.856`, and its LLM-reranked
variant `0.927` at mAP@10. Those values are context, not direct parity results:
the paper used Azure AI Search, `text-embedding-ada-002`, and an optional GPT-4o
reranker. The local paired artifact uses identical frozen E5/RRF seeds for both
graph methods so that the traversal delta is attributable.

## Next external gates

1. **ToolRet:** download the public parquet shards, normalize its 43K catalog and
   7.6K queries, then report NDCG/MAP/Recall at 5, 10, and 20.
2. **Re-Invoke:** implement frozen synthetic multi-view indexing without using
   held-out labels or query-specific generation.
3. **TGR:** audit the released discriminator checkpoint and reproduce its
   API-Bank setting before adding a learned-graph row.
4. **Cross-corpus matrix:** run each available method on both ToolRet and the
   graph-tool-call public corpus with a shared embedding revision.
5. **Model-loop follow-up:** use the same Qwen3.6-27B planner only after retrieval
   parity is frozen, preserving calls, input tokens, and wall latency.

Until those gates are complete, graph-tool-call should claim strong internal
efficiency and external benchmark readiness, not state-of-the-art retrieval.

## First full result

The first complete run used all 573 tools and 1,569 queries with
`intfloat/multilingual-e5-small` pinned at
`fd1525a9fd15316a2d503bf26ab031a61d056e98`. The Graph RAG and graph-tool-call
rows received the same complete BM25+dense RRF ranking.

| Method | mAP@10 | Recall@10 | Target hit@10 | All required@10 |
|---|---:|---:|---:|---:|
| BM25 | 0.166 | 0.236 | 0.906 | 0.020 |
| Dense E5 | 0.224 | 0.278 | **0.985** | 0.036 |
| Hybrid RRF | 0.206 | 0.271 | 0.968 | 0.032 |
| Graph RAG-Tool Fusion protocol | **0.852** | **0.940** | 0.866 | **0.797** |
| graph-tool-call typed traversal | 0.371 | 0.655 | 0.953 | 0.111 |

This establishes two results. First, typed graph traversal materially improves
dependency recall over the flat hybrid baseline. Second, the current frozen
graph-tool-call traversal is not competitive with dependency-closure ordering on
ToolLinkOS. It protects semantic seeds and applies bounded weighted reranking,
whereas Graph RAG-Tool Fusion fills the candidate budget with a target seed's
dependency closure. The latter better matches this benchmark's objective.

The next general improvement should therefore separate **target discovery** from
**dependency completion**. A planner-facing retrieval result needs an explicit
target shortlist and a budgeted required-dependency closure, with direct/required
edges admitted before indirect/optional edges. This must be evaluated on real
OpenAPI contract graphs as well as ToolLinkOS so the library is not tuned to a
fictional benchmark.

## Primary sources

- ToolRet: <https://arxiv.org/abs/2503.01763>
- Re-Invoke: <https://arxiv.org/abs/2408.01875>
- ToolRerank: <https://arxiv.org/abs/2403.06551>
- Graph RAG-Tool Fusion and ToolLinkOS: <https://arxiv.org/abs/2502.07223>
- Tool Graph Retriever: <https://arxiv.org/abs/2508.05152>
- LangGraph Bigtool: <https://github.com/langchain-ai/langgraph-bigtool>
