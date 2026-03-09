"""Unified pipeline benchmark: test multiple retrieval configurations side-by-side."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from benchmarks.config import DATASET_REGISTRY, PipelineConfig
from benchmarks.llm_runner import (
    LLMResult,
    call_ollama,
    call_openai_compatible,
    extract_tool_name,
    tools_to_openai_format,
)
from benchmarks.metrics import recall_at_k
from graph_tool_call import ToolGraph


@dataclass
class PipelineQueryResult:
    """Result of one pipeline on one query."""

    pipeline_name: str
    tool_called: str | None = None
    tool_correct: bool = False
    recall: float = 0.0
    input_tokens: int = 0
    latency_ms: float = 0.0
    candidate_count: int = 0
    retrieved_tools: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class MultiPipelineQueryResult:
    """All pipeline results for a single query."""

    query: str
    category: str = ""
    difficulty: str = ""
    expected_tools: list[str] = field(default_factory=list)
    results: dict[str, PipelineQueryResult] = field(default_factory=dict)


@dataclass
class PipelineMetrics:
    """Aggregated metrics for one pipeline on one dataset."""

    accuracy: float = 0.0
    avg_recall: float = 0.0
    avg_input_tokens: float = 0.0
    avg_latency_ms: float = 0.0
    avg_candidate_count: float = 0.0
    total_queries: int = 0
    correct_count: int = 0
    error_count: int = 0


@dataclass
class PipelineDatasetResult:
    """Results for all pipelines on one dataset."""

    name: str
    tool_count: int = 0
    query_count: int = 0
    queries: list[MultiPipelineQueryResult] = field(default_factory=list)
    metrics: dict[str, PipelineMetrics] = field(default_factory=dict)


@dataclass
class PipelineBenchmarkReport:
    """Complete benchmark report across all datasets and pipelines."""

    timestamp: str = ""
    model: str = ""
    pipeline_names: list[str] = field(default_factory=list)
    datasets: list[PipelineDatasetResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "timestamp": self.timestamp,
            "model": self.model,
            "pipeline_names": self.pipeline_names,
            "datasets": [
                {
                    "name": ds.name,
                    "tool_count": ds.tool_count,
                    "query_count": ds.query_count,
                    "queries": [
                        {
                            "query": q.query,
                            "category": q.category,
                            "difficulty": q.difficulty,
                            "expected_tools": q.expected_tools,
                            "results": {name: asdict(r) for name, r in q.results.items()},
                        }
                        for q in ds.queries
                    ],
                    "metrics": {name: asdict(m) for name, m in ds.metrics.items()},
                }
                for ds in self.datasets
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineBenchmarkReport:
        """Deserialize from dict."""
        report = cls(
            timestamp=data.get("timestamp", ""),
            model=data.get("model", ""),
            pipeline_names=data.get("pipeline_names", []),
        )
        for ds_data in data.get("datasets", []):
            ds = PipelineDatasetResult(
                name=ds_data["name"],
                tool_count=ds_data.get("tool_count", 0),
                query_count=ds_data.get("query_count", 0),
            )
            for q_data in ds_data.get("queries", []):
                mq = MultiPipelineQueryResult(
                    query=q_data["query"],
                    category=q_data.get("category", ""),
                    difficulty=q_data.get("difficulty", ""),
                    expected_tools=q_data.get("expected_tools", []),
                )
                for name, r_data in q_data.get("results", {}).items():
                    mq.results[name] = PipelineQueryResult(**r_data)
                ds.queries.append(mq)
            for name, m_data in ds_data.get("metrics", {}).items():
                ds.metrics[name] = PipelineMetrics(**m_data)
            report.datasets.append(ds)
        return report


class PipelineExecutor:
    """Executes multiple pipelines on the same queries for fair comparison."""

    def __init__(
        self,
        pipelines: list[PipelineConfig],
        model: str,
        ollama_url: str = "http://localhost:11434/api/chat",
        num_ctx: int = 8192,
        timeout: int = 120,
    ) -> None:
        self._pipelines = pipelines
        self._model = model
        self._ollama_url = ollama_url
        self._num_ctx = num_ctx
        self._timeout = timeout
        self._is_openai = "/v1" in ollama_url

    def run_all(
        self,
        datasets: list[str] | None = None,
        verbose: bool = False,
    ) -> PipelineBenchmarkReport:
        """Run all datasets with all pipelines."""
        if datasets is None:
            datasets = [k for k, v in DATASET_REGISTRY.items() if not v.get("legacy")]

        report = PipelineBenchmarkReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=self._model,
            pipeline_names=[p.name for p in self._pipelines],
        )

        for ds_name in datasets:
            reg = DATASET_REGISTRY.get(ds_name)
            if not reg or reg.get("legacy"):
                print(f"  Skipping '{ds_name}' (legacy or unknown)")
                continue

            print(f"\n{'=' * 60}")
            print(f"Dataset: {ds_name}")
            print(f"{'=' * 60}")

            ds_result = self.run_dataset(ds_name, verbose=verbose)
            report.datasets.append(ds_result)

        return report

    def run_dataset(
        self,
        ds_name: str,
        verbose: bool = False,
    ) -> PipelineDatasetResult:
        """Run all queries in a dataset through all pipelines."""
        reg = DATASET_REGISTRY[ds_name]

        with open(reg["ground_truth"]) as f:
            gt = json.load(f)

        # Build ToolGraph instances per pipeline config
        graphs = self._build_tool_graphs(reg["sources"])

        ds_result = PipelineDatasetResult(
            name=gt.get("name", ds_name),
            tool_count=gt.get("tool_count", 0),
            query_count=len(gt["queries"]),
        )

        # If tool_count not in ground truth, infer from first ToolGraph
        if ds_result.tool_count == 0 and graphs:
            first_tg, first_tools = next(iter(graphs.values()))
            ds_result.tool_count = len(first_tg._tools)

        for i, q in enumerate(gt["queries"]):
            query = q["query"]
            expected = set(q["expected_tools"])

            print(f"  [{i + 1}/{len(gt['queries'])}] {query}")

            mq = MultiPipelineQueryResult(
                query=query,
                category=q.get("category", ""),
                difficulty=q.get("difficulty", ""),
                expected_tools=q["expected_tools"],
            )

            for pipeline in self._pipelines:
                tg, all_tools_openai = graphs[pipeline.name]
                result = self._run_query_pipeline(
                    query,
                    expected,
                    pipeline,
                    tg,
                    all_tools_openai,
                )
                mq.results[pipeline.name] = result

                mark = "?" if result.error else ("O" if result.tool_correct else "X")
                suffix = f" err={result.error}" if result.error else ""
                if verbose:
                    print(
                        f"    {pipeline.name}: {mark} "
                        f"tool={result.tool_called} "
                        f"tokens={result.input_tokens} "
                        f"latency={result.latency_ms:.0f}ms"
                        f"{suffix}"
                    )

            # Print compact summary per query
            parts = []
            for p in self._pipelines:
                r = mq.results[p.name]
                mark = "?" if r.error else ("O" if r.tool_correct else "X")
                parts.append(f"{p.name}={mark}({r.tool_called})")
            print(f"    {' | '.join(parts)}")

            ds_result.queries.append(mq)

        self._compute_metrics(ds_result)
        return ds_result

    def _build_tool_graphs(
        self,
        sources: list[dict],
    ) -> dict[str, tuple[ToolGraph, list[dict]]]:
        """Build ToolGraph instances per unique pipeline config.

        Pipelines with same embedding share a ToolGraph.
        Returns {pipeline_name: (tool_graph, all_tools_openai_format)}
        """
        # Group pipelines by (embedding, organize) — same combo shares a ToolGraph
        graph_groups: dict[tuple[str | None, str | None], list[PipelineConfig]] = {}
        for p in self._pipelines:
            key = (p.embedding, p.organize)
            if key not in graph_groups:
                graph_groups[key] = []
            graph_groups[key].append(p)

        # Build one ToolGraph per group
        built: dict[tuple[str | None, str | None], tuple[ToolGraph, list[dict]]] = {}
        for (emb_key, org_key), _group in graph_groups.items():
            tg = self._build_single_tool_graph(sources)

            # Apply organize before embedding (ontology enriches graph first)
            if org_key is not None:
                self._apply_organize(tg, org_key)

            if emb_key is not None:
                tg.enable_embedding(emb_key)
            all_tools_openai = tools_to_openai_format(list(tg._tools.values()))
            built[(emb_key, org_key)] = (tg, all_tools_openai)

        # Map each pipeline name to its shared ToolGraph
        result: dict[str, tuple[ToolGraph, list[dict]]] = {}
        for p in self._pipelines:
            tg, all_tools_openai = built[(p.embedding, p.organize)]
            # Apply custom weights if specified
            if p.weights is not None:
                tg.set_weights(**p.weights)
            # Enable reranker if specified
            if p.reranker is not None:
                tg.enable_reranker(p.reranker)
            result[p.name] = (tg, all_tools_openai)

        return result

    def _apply_organize(self, tg: ToolGraph, org_key: str) -> None:
        """Apply auto_organize to a ToolGraph based on organize key."""
        if org_key == "auto":
            # Auto mode only (tags, domain, embedding clustering) — no LLM
            print("    [organize] auto mode (no LLM)")
            tg.auto_organize()
        elif org_key == "llm":
            # LLM-Auto mode using the benchmark's LLM model
            llm_model = f"ollama/{self._model}"
            print(f"    [organize] LLM-auto mode ({llm_model})")
            tg.auto_organize(llm=llm_model)
        elif org_key.startswith("ollama/") or org_key.startswith("openai/"):
            # Explicit LLM model string
            print(f"    [organize] LLM-auto mode ({org_key})")
            tg.auto_organize(llm=org_key)
        else:
            print(f"    [organize] unknown mode '{org_key}', skipping")

    @staticmethod
    def _build_single_tool_graph(sources: list[dict]) -> ToolGraph:
        """Build a ToolGraph from source configs."""
        tg = ToolGraph()
        for src in sources:
            src_type = src["type"]
            src_path = src["path"]

            if src_type == "openapi":
                tg.ingest_openapi(src_path)
            elif src_type == "mcp":
                with open(src_path) as f:
                    mcp_data = json.load(f)
                tg.ingest_mcp_tools(mcp_data["tools"])
            else:
                print(f"  Warning: unknown source type '{src_type}', skipping")

        return tg

    def _run_query_pipeline(
        self,
        query: str,
        expected: set[str],
        pipeline: PipelineConfig,
        tg: ToolGraph,
        all_tools_openai: list[dict],
    ) -> PipelineQueryResult:
        """Run one query through one pipeline."""
        result = PipelineQueryResult(pipeline_name=pipeline.name)

        try:
            if not pipeline.use_retrieval:
                # Baseline: pass ALL tools to LLM
                tools_for_llm = all_tools_openai
                result.candidate_count = len(tools_for_llm)
                result.recall = 1.0  # all tools present → perfect recall
                result.retrieved_tools = [t["function"]["name"] for t in tools_for_llm]
            else:
                # Retrieval: filter tools first
                retrieved = tg.retrieve(query, top_k=pipeline.top_k)
                retrieved_names = [r.name for r in retrieved]
                result.retrieved_tools = retrieved_names
                result.candidate_count = len(retrieved)
                result.recall = recall_at_k(
                    retrieved_names,
                    expected,
                    pipeline.top_k,
                )
                tools_for_llm = tools_to_openai_format(retrieved)

            # Call LLM
            llm_result = self._call_llm(query, tools_for_llm)

            if llm_result.error:
                result.error = llm_result.error
            else:
                tool_name = extract_tool_name(llm_result)
                result.tool_called = tool_name
                result.tool_correct = tool_name in expected if tool_name else False

            result.input_tokens = llm_result.input_tokens
            result.latency_ms = llm_result.latency * 1000

        except Exception as e:  # noqa: BLE001
            result.error = str(e)

        return result

    def _call_llm(self, query: str, tools: list[dict]) -> LLMResult:
        """Call LLM (auto-detect Ollama vs OpenAI-compatible)."""
        if self._is_openai:
            return call_openai_compatible(
                model=self._model,
                query=query,
                tools=tools,
                base_url=self._ollama_url,
                timeout=self._timeout,
            )
        return call_ollama(
            model=self._model,
            query=query,
            tools=tools,
            ollama_url=self._ollama_url,
            num_ctx=self._num_ctx,
            timeout=self._timeout,
        )

    @staticmethod
    def _compute_metrics(ds_result: PipelineDatasetResult) -> None:
        """Compute aggregated metrics for each pipeline."""
        # Collect all pipeline names from query results
        pipeline_names: set[str] = set()
        for q in ds_result.queries:
            pipeline_names.update(q.results.keys())

        for pname in pipeline_names:
            metrics = PipelineMetrics()
            total_recall = 0.0
            total_tokens = 0
            total_latency = 0.0
            total_candidates = 0

            for q in ds_result.queries:
                r = q.results.get(pname)
                if r is None:
                    continue
                metrics.total_queries += 1
                if r.error:
                    metrics.error_count += 1
                    continue
                if r.tool_correct:
                    metrics.correct_count += 1
                total_recall += r.recall
                total_tokens += r.input_tokens
                total_latency += r.latency_ms
                total_candidates += r.candidate_count

            n = metrics.total_queries
            n_valid = n - metrics.error_count
            if n_valid > 0:
                metrics.accuracy = metrics.correct_count / n_valid
                metrics.avg_recall = total_recall / n_valid
                metrics.avg_input_tokens = total_tokens / n_valid
                metrics.avg_latency_ms = total_latency / n_valid
                metrics.avg_candidate_count = total_candidates / n_valid

            ds_result.metrics[pname] = metrics
