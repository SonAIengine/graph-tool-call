"""ToolLinkOS parity benchmark for dependency-aware tool retrieval.

The adapter intentionally consumes the benchmark's published dependency graph.
It measures retrieval and traversal over a known graph; it does not measure
graph-tool-call's automatic contract extraction or graph construction quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    finalize_artifact,
    validate_artifact,
    write_artifact,
)
from benchmarks.metrics import average_precision, ndcg_at_k, recall_at_k
from benchmarks.paper_baselines.graph_retrievers import FixedGraphRetriever
from benchmarks.paper_baselines.retrievers import (
    DEFAULT_DENSE_MODEL,
    DEFAULT_DENSE_MODEL_REVISION,
    DenseEncoder,
    FixedBM25Retriever,
    FixedDenseRetriever,
    RankedCandidate,
    SentenceTransformerDenseEncoder,
    reciprocal_rank_fusion,
)
from graph_tool_call.core.tool import ToolParameter, ToolSchema
from graph_tool_call.graphify import complete_target_dependencies, select_target_candidate
from graph_tool_call.graphify.edges import EVIDENCE_MANUAL
from graph_tool_call.ontology.schema import Confidence, RelationType
from graph_tool_call.tool_graph import ToolGraph

TOOLLINKOS_COMMIT = "b630b98656e25c3b83a71ea0406572add38ae46d"
TOOLLINKOS_REPOSITORY = "https://github.com/EliasLumer/Graph-RAG-Tool-Fusion-ToolLinkOS"
TOOLLINKOS_LICENSE = "MIT"
TOOLLINKOS_FILES = ("regular_tools.json", "core_tools.json", "instances.json")
PARITY_BASELINES = (
    "bm25",
    "dense",
    "hybrid_rrf",
    "graph_rag_tool_fusion",
    "graph_tool_call_typed",
    "graph_tool_call_closure",
)
GRTF_POLICY_REVISION = "toolinkos-grtf-algorithm-1-v1"
DEPENDENCY_CLOSURE_BENCHMARK_POLICY = "b8-target-preserving-dependency-closure-v1"
PARITY_METHODOLOGY = "toolinkos-paired-external-parity-v1"


@dataclass(frozen=True)
class ToolLinkOSDataset:
    """Normalized ToolLinkOS tools, dependency graph, and query cases."""

    tools: list[ToolSchema]
    dependencies: dict[str, list[str]]
    cases: list[dict[str, Any]]
    source_hashes: dict[str, str]


def download_toollinkos(destination: str | Path) -> Path:
    """Download the three official ToolLinkOS JSON files at a pinned commit."""
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=True)
    base = (
        "https://raw.githubusercontent.com/"
        f"EliasLumer/Graph-RAG-Tool-Fusion-ToolLinkOS/{TOOLLINKOS_COMMIT}/toollinkos"
    )
    for filename in TOOLLINKOS_FILES:
        output = target / filename
        if output.is_file():
            continue
        with urllib.request.urlopen(f"{base}/{filename}", timeout=60) as response:  # noqa: S310
            payload = response.read()
        output.write_bytes(payload)
    return target


def load_toollinkos(dataset_root: str | Path) -> ToolLinkOSDataset:
    """Load and validate a local copy of the official ToolLinkOS dataset."""
    root = Path(dataset_root).resolve()
    missing = [filename for filename in TOOLLINKOS_FILES if not (root / filename).is_file()]
    if missing:
        raise FileNotFoundError(f"ToolLinkOS files missing from {root}: {', '.join(missing)}")

    raw_tools = [
        *_read_list(root / "regular_tools.json"),
        *_read_list(root / "core_tools.json"),
    ]
    tools: list[ToolSchema] = []
    dependencies: dict[str, list[str]] = {}
    known_names: set[str] = set()
    for row in raw_tools:
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError("ToolLinkOS contains a tool without a name.")
        if name in known_names:
            raise ValueError(f"ToolLinkOS contains duplicate tool name: {name}")
        known_names.add(name)
        tools.append(_tool_schema(row))
        dependencies[name] = [
            str(dependency.get("name") or "").strip()
            for dependency in row.get("depends_on") or []
            if str(dependency.get("name") or "").strip()
        ]

    dangling = sorted(
        {
            dependency
            for values in dependencies.values()
            for dependency in values
            if dependency not in known_names
        }
    )
    if dangling:
        raise ValueError(f"ToolLinkOS contains unknown dependencies: {dangling[:10]}")

    cases: list[dict[str, Any]] = []
    for index, row in enumerate(_read_list(root / "instances.json")):
        query = str(row.get("user_query") or "").strip()
        target = str(row.get("main_golden_function_name") or "").strip()
        relevant = [str(name).strip() for name in row.get("golden_function_names") or []]
        if not query or not target or target not in known_names:
            raise ValueError(f"Invalid ToolLinkOS instance at index {index}.")
        unknown_relevant = sorted(set(relevant) - known_names)
        if unknown_relevant:
            raise ValueError(
                f"ToolLinkOS instance {index} references unknown tools: {unknown_relevant[:10]}"
            )
        cases.append(
            {
                "case_id": f"toolinkos-{index:04d}",
                "query": query,
                "expected_target": target,
                "relevant_tools": list(dict.fromkeys(relevant)),
            }
        )

    return ToolLinkOSDataset(
        tools=tools,
        dependencies=dependencies,
        cases=cases,
        source_hashes={filename: _sha256(root / filename) for filename in TOOLLINKOS_FILES},
    )


def graph_rag_tool_fusion_rank(
    seed_ranking: Sequence[RankedCandidate],
    dependencies: dict[str, list[str]],
    *,
    initial_k: int = 3,
    final_k: int = 10,
    dependency_limit: int | None = None,
) -> list[RankedCandidate]:
    """Reproduce Algorithm 1 ordering from Graph RAG-Tool Fusion.

    Each initial retrieval seed is appended, followed by a deterministic DFS
    over its published dependencies. The unique list is truncated to final_k.
    """
    if initial_k <= 0 or final_k <= 0:
        return []
    if dependency_limit is not None and dependency_limit < 0:
        raise ValueError("dependency_limit must be non-negative or None.")

    ordered: list[str] = []
    seen: set[str] = set()
    for seed in seed_ranking[:initial_k]:
        _append_unique(seed.name, ordered, seen)
        dependency_count = 0
        stack = list(reversed(dependencies.get(seed.name, [])))
        expanded: set[str] = set()
        while stack and (dependency_limit is None or dependency_count < dependency_limit):
            dependency = stack.pop()
            if dependency in expanded:
                continue
            expanded.add(dependency)
            if dependency not in seen:
                _append_unique(dependency, ordered, seen)
                dependency_count += 1
            for nested in reversed(dependencies.get(dependency, [])):
                if nested not in expanded:
                    stack.append(nested)
            if len(ordered) >= final_k:
                break
        if len(ordered) >= final_k:
            break
    return [
        RankedCandidate(name=name, score=1.0 / rank)
        for rank, name in enumerate(ordered[:final_k], start=1)
    ]


def graph_tool_call_closure_rank(
    query: str,
    seed_ranking: Sequence[RankedCandidate],
    tools: list[ToolSchema],
    graph: ToolGraph,
    *,
    target_ranking: Sequence[RankedCandidate] | None = None,
    initial_k: int = 3,
    target_shortlist_k: int = 4,
    target_reserve: int = 2,
    final_k: int = 10,
    max_hops: int = 3,
) -> tuple[list[RankedCandidate], dict[str, Any]]:
    """Run B8 target selection followed by role-separated dependency closure."""

    if initial_k <= 0 or final_k <= 0:
        return [], {"reason": "empty_budget"}
    tools_by_name = {tool.name: tool for tool in tools}
    target_surface = list(target_ranking or seed_ranking)
    shortlist = target_surface[: max(initial_k, target_shortlist_k)]
    selection = select_target_candidate(
        query,
        [candidate.name for candidate in shortlist],
        tools_by_name,
        retrieval_results=[
            {"name": candidate.name, "score": candidate.score} for candidate in shortlist
        ],
        llm_target=shortlist[0].name if shortlist else None,
    )
    target = str(selection.get("selected_target") or "")
    closure = complete_target_dependencies(
        target,
        tools_by_name,
        graph=graph,
        max_hops=max_hops,
    )
    ordered = _dedupe_names(
        [
            target,
            *closure.required_dependencies,
            *(candidate.name for candidate in shortlist[:target_reserve]),
            *closure.optional_dependencies,
            *(candidate.name for candidate in shortlist[target_reserve:]),
            *(candidate.name for candidate in seed_ranking),
        ]
    )[:final_k]
    ranking = [
        RankedCandidate(name=name, score=1.0 / rank) for rank, name in enumerate(ordered, start=1)
    ]
    return ranking, {
        "policy_revision": DEPENDENCY_CLOSURE_BENCHMARK_POLICY,
        "target_selector": selection,
        "target_shortlist": [candidate.name for candidate in shortlist],
        "target_reserve": target_reserve,
        "dependency_closure": closure.to_dict(),
    }


def run_toollinkos_parity(
    dataset_root: str | Path,
    *,
    output_path: str | Path = "/tmp/graph-tool-call-toolinkos-parity.json",
    top_k_values: tuple[int, ...] = (10, 20, 30),
    initial_k: int = 3,
    dependency_limit: int | None = None,
    dense_encoder: DenseEncoder | None = None,
    dense_model_name: str = DEFAULT_DENSE_MODEL,
    dense_model_revision: str = DEFAULT_DENSE_MODEL_REVISION,
    dense_device: str = "cpu",
    dense_batch_size: int = 32,
    bootstrap_resamples: int = 2000,
    seed: int = 17,
    created_at: str | None = None,
) -> ExperimentArtifact:
    """Run paired ToolLinkOS baselines and write a validated artifact."""
    normalized_k = tuple(dict.fromkeys(int(value) for value in top_k_values))
    if not normalized_k or any(value <= 0 for value in normalized_k):
        raise ValueError("top_k_values must contain positive integers.")
    if initial_k <= 0:
        raise ValueError("initial_k must be greater than zero.")
    if bootstrap_resamples <= 0:
        raise ValueError("bootstrap_resamples must be greater than zero.")
    dataset = load_toollinkos(dataset_root)
    encoder_provider = "injected" if dense_encoder is not None else "sentence-transformers"
    if dense_encoder is None:
        dense_encoder = SentenceTransformerDenseEncoder(
            model_name=dense_model_name,
            revision=dense_model_revision,
            device=dense_device,
            batch_size=dense_batch_size,
        )
    warmup = getattr(dense_encoder, "warmup", None)
    if callable(warmup):
        warmup()

    bm25 = FixedBM25Retriever(dataset.tools)
    dense = FixedDenseRetriever(dataset.tools, dense_encoder)
    graph = _manual_dependency_graph(dataset)
    typed = FixedGraphRetriever(graph, profile="typed_contract")
    maximum_k = max(normalized_k)
    cases: list[dict[str, Any]] = []

    for raw_case in dataset.cases:
        started = time.perf_counter()
        bm25_ranking = bm25.rank(raw_case["query"], top_k=len(dataset.tools))
        bm25_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        dense_ranking = dense.rank(raw_case["query"], top_k=len(dataset.tools))
        dense_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        hybrid_ranking = reciprocal_rank_fusion(
            [bm25_ranking, dense_ranking],
            top_k=len(dataset.tools),
        )
        hybrid_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        grtf_ranking = graph_rag_tool_fusion_rank(
            hybrid_ranking,
            dataset.dependencies,
            initial_k=initial_k,
            final_k=maximum_k,
            dependency_limit=dependency_limit,
        )
        grtf_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        typed_ranking, typed_diagnostics = typed.rank(
            raw_case["query"],
            hybrid_ranking,
            top_k=maximum_k,
        )
        typed_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        closure_ranking, closure_diagnostics = graph_tool_call_closure_rank(
            raw_case["query"],
            hybrid_ranking,
            dataset.tools,
            graph,
            target_ranking=dense_ranking,
            initial_k=initial_k,
            final_k=maximum_k,
        )
        closure_ms = (time.perf_counter() - started) * 1000

        rankings = {
            "bm25": (bm25_ranking, bm25_ms),
            "dense": (dense_ranking, dense_ms),
            "hybrid_rrf": (hybrid_ranking, bm25_ms + dense_ms + hybrid_ms),
            "graph_rag_tool_fusion": (
                grtf_ranking,
                bm25_ms + dense_ms + hybrid_ms + grtf_ms,
            ),
            "graph_tool_call_typed": (
                typed_ranking,
                bm25_ms + dense_ms + hybrid_ms + typed_ms,
            ),
            "graph_tool_call_closure": (
                closure_ranking,
                bm25_ms + dense_ms + hybrid_ms + closure_ms,
            ),
        }
        relevant = set(raw_case["relevant_tools"])
        results = {
            name: _case_metrics(
                ranking,
                relevant=relevant,
                expected_target=raw_case["expected_target"],
                top_k_values=normalized_k,
                latency_ms=latency_ms,
            )
            for name, (ranking, latency_ms) in rankings.items()
        }
        results["graph_tool_call_typed"]["diagnostics"] = typed_diagnostics
        results["graph_tool_call_closure"]["diagnostics"] = closure_diagnostics
        closure_payload = closure_diagnostics["dependency_closure"]
        closure_names = {
            closure_payload["target"],
            *closure_payload["required_dependencies"],
            *closure_payload["optional_dependencies"],
        }
        target_shortlist = set(closure_diagnostics["target_shortlist"])
        results["graph_tool_call_closure"]["role_metrics"] = {
            "selected_target_hit": float(closure_payload["target"] == raw_case["expected_target"]),
            "target_shortlist_hit": float(raw_case["expected_target"] in target_shortlist),
            "closure_recall": len(relevant.intersection(closure_names)) / len(relevant),
            "closure_all_required": float(relevant.issubset(closure_names)),
        }
        cases.append({**raw_case, "results": results})

    output = str(Path(output_path))
    source_hash = hashlib.sha256(
        json.dumps(dataset.source_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    artifact = ExperimentArtifact(
        benchmark="toolinkos-external-tool-retrieval",
        methodology=PARITY_METHODOLOGY,
        run_kind="deterministic",
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        seed=seed,
        dataset={
            "id": "ToolLinkOS",
            "split": "test",
            "source_sha256": source_hash,
            "source_hashes": dataset.source_hashes,
            "tool_count": len(dataset.tools),
            "case_count": len(dataset.cases),
            "official_commit": TOOLLINKOS_COMMIT,
            "license": TOOLLINKOS_LICENSE,
            "published_graph_supplied": True,
            "automatic_graph_construction_evaluated": False,
        },
        config={
            "top_k_values": list(normalized_k),
            "initial_k": initial_k,
            "dependency_limit": dependency_limit,
            "baselines": list(PARITY_BASELINES),
            "seed_ranking": "unweighted_bm25_dense_rrf",
            "graph_rag_tool_fusion_policy_revision": GRTF_POLICY_REVISION,
            "graph_tool_call_profile": "typed_contract",
            "graph_tool_call_closure_policy_revision": DEPENDENCY_CLOSURE_BENCHMARK_POLICY,
            "graph_tool_call_closure_target_surface": "dense_top_4",
            "graph_tool_call_closure_target_reserve": 2,
            "published_reference_is_not_directly_comparable": True,
            "published_reference_reason": (
                "The paper used Azure AI Search and text-embedding-ada-002; this parity run "
                "uses the same frozen BM25/E5/RRF ranking for both graph methods."
            ),
            "bootstrap_resamples": bootstrap_resamples,
        },
        model={
            "name": dense_model_name,
            "revision": dense_model_revision,
            "provider": encoder_provider,
            "device": dense_device,
            "batch_size": dense_batch_size,
        },
        replay={
            "command": [
                "python",
                "-m",
                "benchmarks.external_tool_retrieval.toollinkos",
                "--dataset-root",
                str(Path(dataset_root)),
                "--out",
                output,
            ],
            "working_directory": ".",
        },
        summary=_summarize(cases, normalized_k),
        statistics=_paired_statistics(
            cases,
            top_k_values=normalized_k,
            seed=seed,
            bootstrap_resamples=bootstrap_resamples,
        ),
        cases=cases,
        source={
            "type": "external_benchmark",
            "sha256": source_hash,
            "repository": TOOLLINKOS_REPOSITORY,
            "commit": TOOLLINKOS_COMMIT,
        },
    )
    finalize_artifact(artifact)
    validation = validate_artifact(artifact)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"ToolLinkOS artifact validation failed: {codes}")
    write_artifact(output_path, artifact)
    return artifact


def _tool_schema(row: dict[str, Any]) -> ToolSchema:
    parameters = [
        ToolParameter(
            name=str(parameter.get("name") or ""),
            type=str(parameter.get("type") or "string"),
            description=str(parameter.get("description") or ""),
            required=bool(parameter.get("required")),
        )
        for parameter in row.get("parameters") or []
    ]
    return ToolSchema(
        name=str(row["name"]),
        description=str(row.get("description") or ""),
        parameters=parameters,
        metadata={
            "source": "toolinkos",
            "toolinkos": {
                "func_type": str(row.get("func_type") or ""),
                "depends_on": list(row.get("depends_on") or []),
            },
        },
    )


def _manual_dependency_graph(dataset: ToolLinkOSDataset) -> ToolGraph:
    graph = ToolGraph()
    graph.add_tools(dataset.tools, detect_dependencies=False)
    rows_by_name = {tool.name: tool for tool in dataset.tools}
    for source, dependency_names in dataset.dependencies.items():
        raw_dependencies = rows_by_name[source].metadata["toolinkos"]["depends_on"]
        raw_by_name = {str(row.get("name") or ""): row for row in raw_dependencies}
        for target in dependency_names:
            raw = raw_by_name[target]
            dependency_type = str(raw.get("dependence_type") or "")
            relation = (
                RelationType.COMPLEMENTARY
                if "INDIRECTLY_DEPENDS_ON" in dependency_type
                else RelationType.REQUIRES
            )
            graph.add_relation(
                source,
                target,
                relation,
                confidence=Confidence.EXTRACTED,
                conf_score=1.0,
                layer=1,
                evidence=(
                    f"toolinkos:{dependency_type or 'dependency'}:{raw.get('parameter_name', '')}"
                ),
            )
            attrs = graph.graph.get_edge_attrs(source, target)
            evidence_sources = list(attrs.get("evidence_sources") or [])
            if EVIDENCE_MANUAL not in evidence_sources:
                evidence_sources.append(EVIDENCE_MANUAL)
            graph.graph.add_edge(
                source,
                target,
                **attrs,
                evidence_sources=evidence_sources,
                is_manual=True,
            )
    return graph


def _case_metrics(
    ranking: Sequence[RankedCandidate],
    *,
    relevant: set[str],
    expected_target: str,
    top_k_values: tuple[int, ...],
    latency_ms: float,
) -> dict[str, Any]:
    names = [candidate.name for candidate in ranking]
    result: dict[str, Any] = {
        "ranking": names[: max(top_k_values)],
        "latency_ms": latency_ms,
    }
    for top_k in top_k_values:
        prefix = names[:top_k]
        result[f"map_at_{top_k}"] = average_precision(prefix, relevant)
        result[f"recall_at_{top_k}"] = recall_at_k(prefix, relevant, top_k)
        result[f"ndcg_at_{top_k}"] = ndcg_at_k(prefix, relevant, top_k)
        result[f"target_hit_at_{top_k}"] = float(expected_target in prefix)
        result[f"all_required_at_{top_k}"] = float(relevant.issubset(prefix))
    return result


def _summarize(cases: list[dict[str, Any]], top_k_values: tuple[int, ...]) -> dict[str, Any]:
    if not cases:
        return {
            "case_count": 0,
            "baselines": {},
            "graph_tool_call_closure_role_metrics": {},
        }
    metrics = [
        *(f"map_at_{top_k}" for top_k in top_k_values),
        *(f"recall_at_{top_k}" for top_k in top_k_values),
        *(f"ndcg_at_{top_k}" for top_k in top_k_values),
        *(f"target_hit_at_{top_k}" for top_k in top_k_values),
        *(f"all_required_at_{top_k}" for top_k in top_k_values),
        "latency_ms",
    ]
    summary = {
        "case_count": len(cases),
        "baselines": {
            baseline: {
                metric: fmean(case["results"][baseline][metric] for case in cases)
                for metric in metrics
            }
            for baseline in PARITY_BASELINES
        },
    }
    role_metrics = cases[0]["results"]["graph_tool_call_closure"].get("role_metrics", {})
    summary["graph_tool_call_closure_role_metrics"] = {
        metric: fmean(
            case["results"]["graph_tool_call_closure"]["role_metrics"][metric] for case in cases
        )
        for metric in role_metrics
    }
    return summary


def _paired_statistics(
    cases: list[dict[str, Any]],
    *,
    top_k_values: tuple[int, ...],
    seed: int,
    bootstrap_resamples: int,
) -> dict[str, Any]:
    primary_k = min(top_k_values)
    metrics = (
        f"map_at_{primary_k}",
        f"recall_at_{primary_k}",
        f"target_hit_at_{primary_k}",
        f"all_required_at_{primary_k}",
        "latency_ms",
    )
    comparisons = {
        "grtf_minus_hybrid": ("hybrid_rrf", "graph_rag_tool_fusion"),
        "typed_minus_hybrid": ("hybrid_rrf", "graph_tool_call_typed"),
        "typed_minus_grtf": ("graph_rag_tool_fusion", "graph_tool_call_typed"),
        "closure_minus_hybrid": ("hybrid_rrf", "graph_tool_call_closure"),
        "closure_minus_typed": ("graph_tool_call_typed", "graph_tool_call_closure"),
        "closure_minus_grtf": ("graph_rag_tool_fusion", "graph_tool_call_closure"),
    }
    return {
        "method": "paired_case_bootstrap",
        "resamples": bootstrap_resamples,
        "confidence": 0.95,
        "comparisons": {
            name: {
                metric: _paired_delta(
                    cases,
                    baseline=baseline,
                    candidate=candidate,
                    metric=metric,
                    seed=seed + comparison_index * 100 + metric_index,
                    bootstrap_resamples=bootstrap_resamples,
                )
                for metric_index, metric in enumerate(metrics)
            }
            for comparison_index, (name, (baseline, candidate)) in enumerate(comparisons.items())
        },
    }


def _paired_delta(
    cases: list[dict[str, Any]],
    *,
    baseline: str,
    candidate: str,
    metric: str,
    seed: int,
    bootstrap_resamples: int,
) -> dict[str, float]:
    deltas = [
        float(case["results"][candidate][metric]) - float(case["results"][baseline][metric])
        for case in cases
    ]
    rng = random.Random(seed)
    count = len(deltas)
    means = sorted(
        sum(deltas[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(bootstrap_resamples)
    )
    lower_index = max(0, int(0.025 * bootstrap_resamples))
    upper_index = min(bootstrap_resamples - 1, int(0.975 * bootstrap_resamples))
    return {
        "mean_delta": fmean(deltas),
        "ci95_low": means[lower_index],
        "ci95_high": means[upper_index],
    }


def _append_unique(name: str, ordered: list[str], seen: set[str]) -> None:
    if name and name not in seen:
        ordered.append(name)
        seen.add(name)


def _dedupe_names(names: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(name) for name in names if str(name)))


def _read_list(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"Expected a JSON object list: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_top_k(value: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("top-k must be comma-separated integers") from exc
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("top-k must contain positive integers")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ToolLinkOS external parity benchmark.")
    parser.add_argument("--dataset-root", default="/tmp/toolinkos")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--out", default="/tmp/graph-tool-call-toolinkos-parity.json")
    parser.add_argument("--top-k", type=_parse_top_k, default=(10, 20, 30))
    parser.add_argument("--initial-k", type=int, default=3)
    parser.add_argument("--dependency-limit", type=int)
    parser.add_argument("--dense-model", default=DEFAULT_DENSE_MODEL)
    parser.add_argument("--dense-revision", default=DEFAULT_DENSE_MODEL_REVISION)
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-batch-size", type=int, default=32)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)
    if args.download:
        download_toollinkos(args.dataset_root)
    artifact = run_toollinkos_parity(
        args.dataset_root,
        output_path=args.out,
        top_k_values=args.top_k,
        initial_k=args.initial_k,
        dependency_limit=args.dependency_limit,
        dense_model_name=args.dense_model,
        dense_model_revision=args.dense_revision,
        dense_device=args.dense_device,
        dense_batch_size=args.dense_batch_size,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    print(json.dumps(artifact.summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
