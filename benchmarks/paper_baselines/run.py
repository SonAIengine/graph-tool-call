"""Run frozen random, oracle, lexical, dense, hybrid, and flat-semantic baselines."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from benchmarks.corpus.manifest import (
    DEFAULT_MANIFEST_PATH,
    load_corpus_manifest,
    validate_corpus_manifest,
)
from benchmarks.experiment.artifact import (
    ExperimentArtifact,
    finalize_artifact,
    validate_artifact,
    write_artifact,
)
from benchmarks.metrics import (
    average_precision,
    confidence_interval,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from graph_tool_call import ingest_source
from graph_tool_call.core.tool import ToolSchema

from .retrievers import (
    DEFAULT_DENSE_MODEL,
    DEFAULT_DENSE_MODEL_REVISION,
    FIXED_BM25_TOKENIZER_REVISION,
    FIXED_RRF_K,
    DenseEncoder,
    FixedBM25Retriever,
    FixedDenseRetriever,
    RankedCandidate,
    SentenceTransformerDenseEncoder,
    flat_semantic_coverage,
    flat_semantic_document,
    oracle_rank,
    reciprocal_rank_fusion,
    seeded_random_rank,
)

BASELINE_NAMES = (
    "seeded_random",
    "oracle",
    "bm25",
    "dense",
    "hybrid_rrf",
    "flat_semantic_rrf",
)
PRIMARY_METRICS = (
    "target_hit_at_k",
    "producer_recall_at_k",
    "required_tool_recall_at_k",
    "all_required_found_at_k",
    "precision_at_k",
    "mrr",
    "average_precision",
    "ndcg_at_k",
)
STATISTICAL_METRICS = (*PRIMARY_METRICS, "latency_ms")


def run_paper_baselines(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    splits: tuple[str, ...] = ("train", "dev"),
    top_k: int = 5,
    seed: int = 17,
    output_path: str | Path = "/tmp/graph-tool-call-paper-baselines.json",
    allow_held_out: bool = False,
    created_at: str | None = None,
    dense_encoder: DenseEncoder | None = None,
    dense_model_name: str = DEFAULT_DENSE_MODEL,
    dense_model_revision: str = DEFAULT_DENSE_MODEL_REVISION,
    dense_device: str = "cpu",
    dense_batch_size: int = 32,
) -> ExperimentArtifact:
    """Evaluate the six frozen baselines and return one paired artifact."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")
    if not dense_model_name.strip() or not dense_model_revision.strip():
        raise ValueError("dense_model_name and dense_model_revision must be non-empty.")
    if dense_batch_size <= 0:
        raise ValueError("dense_batch_size must be greater than zero.")
    normalized_splits = tuple(dict.fromkeys(split.strip() for split in splits if split.strip()))
    invalid_splits = sorted(set(normalized_splits) - {"train", "dev", "test"})
    if not normalized_splits or invalid_splits:
        raise ValueError(f"splits must contain train, dev, or test; invalid={invalid_splits}")
    if "test" in normalized_splits and not allow_held_out:
        raise ValueError("Held-out test access requires --allow-held-out.")

    resolved_manifest = Path(manifest_path).resolve()
    report = validate_corpus_manifest(
        resolved_manifest,
        verify_hashes=True,
        verify_ingest=True,
    )
    if not report.integrity_ready:
        blockers = [
            issue.code
            for issue in report.issues
            if issue.scope == "integrity" and issue.severity == "blocker"
        ]
        raise ValueError(f"Corpus integrity validation failed: {', '.join(blockers)}")
    if "test" in normalized_splits:
        if not report.paper_ready:
            raise ValueError(
                "Held-out test access is blocked until the corpus paper-readiness gate passes."
            )

    manifest = load_corpus_manifest(resolved_manifest)
    manifest_root = resolved_manifest.parent
    encoder_provider = "injected"
    encoder_library = f"{type(dense_encoder).__module__}.{type(dense_encoder).__qualname__}"
    encoder_library_version = ""
    if dense_encoder is None:
        dense_encoder = SentenceTransformerDenseEncoder(
            model_name=dense_model_name,
            revision=dense_model_revision,
            device=dense_device,
            batch_size=dense_batch_size,
        )
        encoder_provider = "sentence-transformers"
        encoder_library = "sentence-transformers"
        encoder_library_version = _package_version("sentence-transformers")
    started = time.perf_counter()
    warmup = getattr(dense_encoder, "warmup", None)
    if callable(warmup):
        warmup()
    dense_model_load_ms = (time.perf_counter() - started) * 1000
    selected_sources = [
        source
        for source in manifest["sources"]
        if source.get("paper_core") is True and source.get("split") in normalized_splits
    ]
    cases: list[dict[str, Any]] = []
    for source in selected_sources:
        tools = _load_source_tools(source, manifest_root)
        ground_truth = _read_json(manifest_root / source["ground_truth_path"])
        cases.extend(
            _evaluate_source(
                source,
                tools,
                ground_truth["cases"],
                top_k=top_k,
                seed=seed,
                dense_encoder=dense_encoder,
                dense_model_load_ms=dense_model_load_ms,
            )
        )

    summary, statistics = _summarize(cases, seed=seed)
    manifest_sha256 = _sha256(resolved_manifest)
    output = str(Path(output_path))
    replay_command = [
        "python",
        "-m",
        "benchmarks.paper_baselines.run",
        "--manifest",
        str(manifest_path),
        "--splits",
        ",".join(normalized_splits),
        "--top-k",
        str(top_k),
        "--seed",
        str(seed),
        "--out",
        output,
        "--dense-model",
        dense_model_name,
        "--dense-revision",
        dense_model_revision,
        "--dense-device",
        dense_device,
        "--dense-batch-size",
        str(dense_batch_size),
    ]
    if allow_held_out:
        replay_command.append("--allow-held-out")
    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-tool-retrieval",
        methodology="paired-fixed-baselines-v2",
        run_kind="deterministic",
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        seed=seed,
        dataset={
            "id": manifest["corpus_id"],
            "split": normalized_splits[0] if len(normalized_splits) == 1 else "mixed",
            "splits": list(normalized_splits),
            "manifest_sha256": manifest_sha256,
            "held_out_accessed": "test" in normalized_splits,
        },
        config={
            "top_k": top_k,
            "budget": {
                "type": "candidate_count",
                "limit": top_k,
                "actual_token_budget_claimed": False,
            },
            "baselines": {
                "seeded_random": {
                    "label": "B-1",
                    "seed_derivation": "sha256(global_seed:source_id:case_id)",
                },
                "oracle": {
                    "label": "B0-O",
                    "ordering": ["expected_targets", "required_producers", "alternatives"],
                    "fills_with_distractors": False,
                },
                "bm25": {
                    "label": "B1",
                    "k1": 1.2,
                    "b": 0.75,
                    "fields": ["name", "ai_metadata.one_line_summary", "description"],
                    "tokenizer_revision": FIXED_BM25_TOKENIZER_REVISION,
                    "query_expansion": False,
                    "graph_signals": False,
                },
                "dense": {
                    "label": "B2",
                    "model": dense_model_name,
                    "revision": dense_model_revision,
                    "document_prefix": "passage: ",
                    "query_prefix": "query: ",
                    "fields": ["name", "ai_metadata.one_line_summary", "description"],
                    "similarity": "cosine",
                    "normalized_embeddings": True,
                    "device": dense_device,
                    "batch_size": dense_batch_size,
                },
                "hybrid_rrf": {
                    "label": "B3",
                    "channels": ["bm25", "dense"],
                    "fusion": "unweighted_reciprocal_rank_fusion",
                    "rrf_k": FIXED_RRF_K,
                },
                "flat_semantic_rrf": {
                    "label": "B4",
                    "channels": ["flat_semantic_bm25", "flat_semantic_dense"],
                    "fusion": "unweighted_reciprocal_rank_fusion",
                    "rrf_k": FIXED_RRF_K,
                    "base_fields": [
                        "name",
                        "ai_metadata.one_line_summary",
                        "description",
                    ],
                    "semantic_fields": [
                        "ai_metadata.canonical_action",
                        "ai_metadata.primary_resource",
                        "openapi.path_module",
                        "ai_metadata.result_shape",
                    ],
                    "openapi_semantic_derivation": "derive_openapi_tool_semantics",
                    "query_expansion": False,
                    "graph_signals": False,
                    "contract_signals": False,
                    "selector_signals": False,
                },
            },
        },
        model={
            "name": dense_model_name,
            "provider": encoder_provider,
            "revision": dense_model_revision,
            "role": "embedding",
            "library": encoder_library,
            "library_version": encoder_library_version,
        },
        replay={
            "command": replay_command,
            "working_directory": ".",
        },
        summary=summary,
        statistics=statistics,
        cases=cases,
        source={
            "type": "paper_baseline_manifest",
            "sha256": manifest_sha256,
        },
    )
    finalize_artifact(artifact)
    validation = validate_artifact(artifact)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ValueError(f"Generated experiment artifact is invalid: {codes}")
    return artifact


def _load_source_tools(source: dict[str, Any], manifest_root: Path) -> list[ToolSchema]:
    raw_source = _read_json(manifest_root / source["snapshot_path"])
    result = ingest_source(
        raw_source,
        format_hint=source["adapter"],
        **(source.get("ingest_options") or {}),
    )
    unique: dict[str, ToolSchema] = {}
    for tool in result.tools:
        unique.setdefault(tool.name, tool)
    return sorted(unique.values(), key=lambda tool: (tool.name.casefold(), tool.name))


def _evaluate_source(
    source: dict[str, Any],
    tools: list[ToolSchema],
    ground_truth_cases: list[dict[str, Any]],
    *,
    top_k: int,
    seed: int,
    dense_encoder: DenseEncoder,
    dense_model_load_ms: float,
) -> list[dict[str, Any]]:
    bm25 = FixedBM25Retriever(tools)
    dense = FixedDenseRetriever(tools, dense_encoder)
    started = time.perf_counter()
    flat_semantic_documents = {tool.name: flat_semantic_document(tool) for tool in tools}
    flat_semantic_document_build_ms = (time.perf_counter() - started) * 1000

    def build_flat_semantic_document(tool: ToolSchema) -> str:
        return flat_semantic_documents[tool.name]

    flat_semantic_bm25 = FixedBM25Retriever(
        tools,
        document_builder=build_flat_semantic_document,
    )
    flat_semantic_dense = FixedDenseRetriever(
        tools,
        dense_encoder,
        document_builder=build_flat_semantic_document,
    )
    semantic_coverage = flat_semantic_coverage(tools)
    available_names = {tool.name for tool in tools}
    tools_by_name = {tool.name: tool for tool in tools}
    evaluated: list[dict[str, Any]] = []
    for case in ground_truth_cases:
        rankings: dict[str, list[RankedCandidate]] = {}
        latencies: dict[str, float] = {}

        started = time.perf_counter()
        rankings["seeded_random"] = seeded_random_rank(
            tools,
            top_k=top_k,
            seed=seed,
            source_id=source["id"],
            case_id=case["case_id"],
        )
        latencies["seeded_random"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        rankings["oracle"] = oracle_rank(
            expected_targets=case["expected_targets"],
            required_producers=case.get("required_producers", []),
            acceptable_alternatives=case.get("acceptable_alternatives", []),
            available_names=available_names,
            top_k=top_k,
        )
        latencies["oracle"] = (time.perf_counter() - started) * 1000

        full_ranking_size = len(tools)
        started = time.perf_counter()
        bm25_full = bm25.rank(case["query"], top_k=full_ranking_size)
        latencies["bm25"] = (time.perf_counter() - started) * 1000
        rankings["bm25"] = bm25_full[:top_k]

        started = time.perf_counter()
        dense_full = dense.rank(case["query"], top_k=full_ranking_size)
        latencies["dense"] = (time.perf_counter() - started) * 1000
        rankings["dense"] = dense_full[:top_k]

        started = time.perf_counter()
        rankings["hybrid_rrf"] = reciprocal_rank_fusion(
            [bm25_full, dense_full],
            top_k=top_k,
        )
        fusion_latency_ms = (time.perf_counter() - started) * 1000
        latencies["hybrid_rrf"] = latencies["bm25"] + latencies["dense"] + fusion_latency_ms

        started = time.perf_counter()
        flat_semantic_bm25_full = flat_semantic_bm25.rank(
            case["query"],
            top_k=full_ranking_size,
        )
        flat_semantic_bm25_latency_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        flat_semantic_dense_full = flat_semantic_dense.rank(
            case["query"],
            top_k=full_ranking_size,
        )
        flat_semantic_dense_latency_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        rankings["flat_semantic_rrf"] = reciprocal_rank_fusion(
            [flat_semantic_bm25_full, flat_semantic_dense_full],
            top_k=top_k,
        )
        flat_semantic_fusion_ms = (time.perf_counter() - started) * 1000
        latencies["flat_semantic_rrf"] = (
            flat_semantic_bm25_latency_ms + flat_semantic_dense_latency_ms + flat_semantic_fusion_ms
        )

        observed: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        for baseline_name, ranking in rankings.items():
            retrieved = [candidate.name for candidate in ranking]
            observed[baseline_name] = {
                "retrieved": retrieved,
                "scores": [
                    {"name": candidate.name, "score": candidate.score} for candidate in ranking
                ],
            }
            metrics[baseline_name] = _case_metrics(
                retrieved,
                case,
                top_k=top_k,
                tools_by_name=tools_by_name,
                latency_ms=latencies[baseline_name],
            )

        evaluated.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "context": {
                    "source_id": source["id"],
                    "family_id": source["family_id"],
                    "split": source["split"],
                    "source_type": source["source_type"],
                    "domain": source.get("domain", ""),
                    "tool_count": len(tools),
                    "baseline_setup_ms": {
                        "dense_model_load": dense_model_load_ms,
                        "bm25_index_build": bm25.build_latency_ms,
                        "dense_document_encoding": dense.build_latency_ms,
                        "flat_semantic_document_build": flat_semantic_document_build_ms,
                        "flat_semantic_bm25_index_build": flat_semantic_bm25.build_latency_ms,
                        "flat_semantic_dense_document_encoding": (
                            flat_semantic_dense.build_latency_ms
                        ),
                    },
                    "flat_semantic_coverage": semantic_coverage,
                },
                "expected": {
                    "expected_targets": list(case["expected_targets"]),
                    "required_producers": list(case.get("required_producers", [])),
                    "acceptable_alternatives": list(case.get("acceptable_alternatives", [])),
                },
                "observed": observed,
                "metrics": metrics,
                "stages": {},
                "failure": {},
            }
        )
    return evaluated


def _case_metrics(
    retrieved: list[str],
    case: dict[str, Any],
    *,
    top_k: int,
    tools_by_name: dict[str, ToolSchema],
    latency_ms: float,
) -> dict[str, Any]:
    expected_targets = set(case["expected_targets"])
    producers = set(case.get("required_producers", []))
    alternatives = set(case.get("acceptable_alternatives", []))
    target_options = expected_targets | alternatives
    required_tools = expected_targets | producers
    broadly_relevant = required_tools | alternatives
    relevance_grades = {name: 1 for name in alternatives}
    relevance_grades.update({name: 2 for name in producers})
    relevance_grades.update({name: 3 for name in expected_targets})
    serialized = [
        json.dumps(
            _model_facing_schema(tools_by_name[name]),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for name in retrieved
        if name in tools_by_name
    ]
    schema_text = "\n".join(serialized)
    return {
        "target_hit_at_k": float(any(name in target_options for name in retrieved[:top_k])),
        "producer_recall_at_k": recall_at_k(retrieved, producers, top_k),
        "required_tool_recall_at_k": recall_at_k(retrieved, required_tools, top_k),
        "all_required_found_at_k": float(required_tools.issubset(set(retrieved[:top_k]))),
        "precision_at_k": precision_at_k(retrieved, broadly_relevant, top_k),
        "mrr": mrr(retrieved, target_options),
        "average_precision": average_precision(retrieved, broadly_relevant),
        "ndcg_at_k": ndcg_at_k(retrieved, relevance_grades, top_k),
        "candidate_count": len(retrieved),
        "schema_chars": len(schema_text),
        "schema_utf8_bytes": len(schema_text.encode("utf-8")),
        "latency_ms": latency_ms,
    }


def _model_facing_schema(tool: ToolSchema) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": [parameter.to_dict() for parameter in tool.parameters],
    }


def _summarize(
    cases: list[dict[str, Any]],
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    per_baseline = {baseline: _aggregate_metrics(cases, baseline) for baseline in BASELINE_NAMES}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["context"]["source_id"]].append(case)
    per_source = {
        source_id: {
            baseline: _aggregate_metrics(source_cases, baseline) for baseline in BASELINE_NAMES
        }
        for source_id, source_cases in sorted(grouped.items())
    }
    split_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        split_counts[case["context"]["split"]] += 1
    summary = {
        "case_count": len(cases),
        "family_count": len({case["context"]["family_id"] for case in cases}),
        "source_count": len(grouped),
        "split_case_counts": dict(sorted(split_counts.items())),
        "baselines": per_baseline,
        "per_source": per_source,
        "setup": {
            "dense_model_load_ms": (
                cases[0]["context"]["baseline_setup_ms"]["dense_model_load"] if cases else 0.0
            ),
            "bm25_index_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"]["bm25_index_build"]
                for source_id, source_cases in sorted(grouped.items())
            },
            "dense_document_encoding_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "dense_document_encoding"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "flat_semantic_document_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "flat_semantic_document_build"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "flat_semantic_bm25_index_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "flat_semantic_bm25_index_build"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "flat_semantic_dense_document_encoding_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "flat_semantic_dense_document_encoding"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "flat_semantic_coverage_by_source": {
                source_id: source_cases[0]["context"]["flat_semantic_coverage"]
                for source_id, source_cases in sorted(grouped.items())
            },
        },
    }
    statistics = {
        "bootstrap": {
            baseline: {
                metric: {
                    "confidence": 0.95,
                    "n_resamples": 1000,
                    "mean_ci": list(
                        confidence_interval(
                            _metric_values(cases, baseline, metric),
                            seed=seed,
                        )
                    ),
                }
                for metric in STATISTICAL_METRICS
            }
            for baseline in BASELINE_NAMES
        }
    }
    return summary, statistics


def _aggregate_metrics(cases: list[dict[str, Any]], baseline: str) -> dict[str, float]:
    if not cases:
        return {metric: 0.0 for metric in PRIMARY_METRICS}
    metric_names = (
        *PRIMARY_METRICS,
        "candidate_count",
        "schema_chars",
        "schema_utf8_bytes",
        "latency_ms",
    )
    result = {metric: fmean(_metric_values(cases, baseline, metric)) for metric in metric_names}
    result["producer_case_count"] = float(
        sum(bool(case["expected"]["required_producers"]) for case in cases)
    )
    return result


def _metric_values(
    cases: list[dict[str, Any]],
    baseline: str,
    metric: str,
) -> list[float]:
    selected = cases
    if metric == "producer_recall_at_k":
        selected = [case for case in cases if case["expected"]["required_producers"]]
    return [float(case["metrics"][baseline][metric]) for case in selected] or [0.0]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--splits", default="train,dev")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-held-out", action="store_true")
    parser.add_argument("--dense-model", default=DEFAULT_DENSE_MODEL)
    parser.add_argument("--dense-revision", default=DEFAULT_DENSE_MODEL_REVISION)
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-batch-size", type=int, default=32)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    artifact = run_paper_baselines(
        args.manifest,
        splits=tuple(args.splits.split(",")),
        top_k=args.top_k,
        seed=args.seed,
        output_path=args.out,
        allow_held_out=args.allow_held_out,
        dense_model_name=args.dense_model,
        dense_model_revision=args.dense_revision,
        dense_device=args.dense_device,
        dense_batch_size=args.dense_batch_size,
    )
    write_artifact(args.out, artifact)
    print(
        json.dumps(
            {
                "artifact": args.out,
                "artifact_id": artifact.artifact_id,
                "case_count": artifact.summary["case_count"],
                "family_count": artifact.summary["family_count"],
                "metrics": artifact.summary["baselines"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
