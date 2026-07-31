"""Run frozen flat, graph, contract, and full-pipeline paper baselines."""

from __future__ import annotations

import argparse
import copy
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
from graph_tool_call.graphify import (
    CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION,
    ingest_openapi_graphify,
)

from .graph_retrievers import (
    FIXED_GRAPH_ADMISSION_POLICY_REVISION,
    FIXED_GRAPH_ADMISSION_RESERVED_SLOTS,
    FIXED_GRAPH_DEPTH,
    FIXED_GRAPH_POLICY_REVISION,
    FIXED_GRAPH_SEED_COUNT,
    FIXED_PRODUCER_MAX_HOPS,
    FIXED_PRODUCERS_PER_FIELD,
    FixedGraphRetriever,
    full_graph_pipeline_rank,
)
from .producer_coverage import (
    PRODUCER_COVERAGE_POLICY_REVISION,
    diagnose_required_producer_coverage,
    summarize_producer_edge_coverage,
)
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
from .token_budget import (
    CONTRACT_PROJECTED_DESCRIPTION_LIMIT,
    CONTRACT_PROJECTED_ENUM_LIMIT,
    CONTRACT_PROJECTED_PARAMETER_DESCRIPTION_LIMIT,
    CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION,
    DEFAULT_CONTEXT_TOKENIZER,
    DEFAULT_CONTEXT_TOKENIZER_REVISION,
    DEFAULT_TOKEN_BUDGET,
    TOKEN_BUDGET_POLICY_REVISION,
    TOOL_SCHEMA_SERIALIZATION_REVISION,
    HuggingFaceTokenCounter,
    TokenCounter,
    apply_contract_projected_token_budget,
    apply_ranked_token_budget,
    model_facing_schema,
)

BASELINE_NAMES = (
    "seeded_random",
    "oracle",
    "bm25",
    "dense",
    "hybrid_rrf",
    "flat_semantic_rrf",
    "graph_untyped",
    "graph_typed_contract",
    "graph_consumer_aligned_contract",
    "graph_consumer_aligned_admission",
    "graph_budget_aware_schema_admission",
    "full_graph_pipeline",
)
ABLATION_PAIRS = {
    "b5_minus_b4_topology": ("flat_semantic_rrf", "graph_untyped"),
    "b6_minus_b5_typed_contract": ("graph_untyped", "graph_typed_contract"),
    "b6a_minus_b6_output_promotion": (
        "graph_typed_contract",
        "graph_consumer_aligned_contract",
    ),
    "b6b_minus_b6a_candidate_admission": (
        "graph_consumer_aligned_contract",
        "graph_consumer_aligned_admission",
    ),
    "b6c_minus_b6b_contract_projection": (
        "graph_consumer_aligned_admission",
        "graph_budget_aware_schema_admission",
    ),
    "b7_minus_b6_selector_producers": (
        "graph_typed_contract",
        "full_graph_pipeline",
    ),
    "b7_minus_b4_full_pipeline": (
        "flat_semantic_rrf",
        "full_graph_pipeline",
    ),
}
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
_COST_METRICS = {
    "latency_ms",
    "schema_tokens",
    "token_budget_used",
    "truncated",
}


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
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    token_counter: TokenCounter | None = None,
    context_tokenizer_name: str = DEFAULT_CONTEXT_TOKENIZER,
    context_tokenizer_revision: str = DEFAULT_CONTEXT_TOKENIZER_REVISION,
    bootstrap_resamples: int = 1000,
) -> ExperimentArtifact:
    """Evaluate the twelve frozen baselines and return one paired artifact."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")
    if not dense_model_name.strip() or not dense_model_revision.strip():
        raise ValueError("dense_model_name and dense_model_revision must be non-empty.")
    if dense_batch_size <= 0:
        raise ValueError("dense_batch_size must be greater than zero.")
    if token_budget <= 0:
        raise ValueError("token_budget must be greater than zero.")
    if not context_tokenizer_name.strip() or not context_tokenizer_revision.strip():
        raise ValueError("context_tokenizer_name and context_tokenizer_revision must be non-empty.")
    if bootstrap_resamples <= 0:
        raise ValueError("bootstrap_resamples must be greater than zero.")
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
    tokenizer_provider = "injected"
    tokenizer_library = f"{type(token_counter).__module__}.{type(token_counter).__qualname__}"
    tokenizer_library_version = ""
    if token_counter is None:
        token_counter = HuggingFaceTokenCounter(
            name=context_tokenizer_name,
            revision=context_tokenizer_revision,
        )
        tokenizer_provider = "huggingface"
        tokenizer_library = "transformers"
        tokenizer_library_version = _package_version("transformers")
    started = time.perf_counter()
    warmup = getattr(dense_encoder, "warmup", None)
    if callable(warmup):
        warmup()
    dense_model_load_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    tokenizer_warmup = getattr(token_counter, "warmup", None)
    if callable(tokenizer_warmup):
        tokenizer_warmup()
    tokenizer_load_ms = (time.perf_counter() - started) * 1000
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
                token_counter=token_counter,
                token_budget=token_budget,
                tokenizer_load_ms=tokenizer_load_ms,
            )
        )

    summary, statistics = _summarize(
        cases,
        seed=seed,
        bootstrap_resamples=bootstrap_resamples,
    )
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
        "--token-budget",
        str(token_budget),
        "--context-tokenizer",
        context_tokenizer_name,
        "--context-tokenizer-revision",
        context_tokenizer_revision,
        "--bootstrap-resamples",
        str(bootstrap_resamples),
    ]
    if allow_held_out:
        replay_command.append("--allow-held-out")
    artifact = ExperimentArtifact(
        benchmark="public-heterogeneous-tool-retrieval",
        methodology="paired-fixed-baselines-v8",
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
            "bootstrap_resamples": bootstrap_resamples,
            "budget": {
                "type": "candidate_count",
                "limit": top_k,
                "actual_token_budget_claimed": False,
            },
            "token_budget": {
                "type": "model_facing_schema_tokens",
                "limit": token_budget,
                "candidate_limit": top_k,
                "policy_revision": TOKEN_BUDGET_POLICY_REVISION,
                "alternate_policy_revisions": {
                    "graph_budget_aware_schema_admission": (
                        CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION
                    )
                },
                "serialization_revision": TOOL_SCHEMA_SERIALIZATION_REVISION,
                "add_special_tokens": False,
                "payload_scope": ["name", "description", "parameters"],
                "query_tokens_included": False,
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
                "graph_untyped": {
                    "label": "B5",
                    "base_ranking": "flat_semantic_rrf",
                    "policy_revision": FIXED_GRAPH_POLICY_REVISION,
                    "profile": "untyped_topology",
                    "seed_count": FIXED_GRAPH_SEED_COUNT,
                    "depth": FIXED_GRAPH_DEPTH,
                    "score_combination": "seed_score_or_max_graph_path",
                    "edge_weights": "uniform",
                    "confidence_weights": False,
                    "contract_signals": False,
                    "selector_signals": False,
                },
                "graph_typed_contract": {
                    "label": "B6",
                    "base_ranking": "flat_semantic_rrf",
                    "policy_revision": FIXED_GRAPH_POLICY_REVISION,
                    "profile": "typed_contract",
                    "seed_count": FIXED_GRAPH_SEED_COUNT,
                    "depth": FIXED_GRAPH_DEPTH,
                    "score_combination": "seed_score_or_max_graph_path",
                    "edge_weights": "frozen_intent_relation_weights",
                    "confidence_weights": True,
                    "contract_signals": True,
                    "selector_signals": False,
                },
                "graph_consumer_aligned_contract": {
                    "label": "B6a",
                    "base_ranking": "flat_semantic_rrf",
                    "policy_revision": FIXED_GRAPH_POLICY_REVISION,
                    "profile": "typed_contract",
                    "seed_count": FIXED_GRAPH_SEED_COUNT,
                    "depth": FIXED_GRAPH_DEPTH,
                    "score_combination": "seed_score_or_max_graph_path",
                    "edge_weights": "frozen_intent_relation_weights",
                    "confidence_weights": True,
                    "contract_signals": True,
                    "output_promotion_policy_revision": (CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION),
                    "output_promotion_scope": "required_data_consumers",
                    "max_consumer_aligned_paths_per_field": 1,
                    "optional_consumer_evidence": False,
                    "ground_truth_signals": False,
                    "selector_signals": False,
                },
                "graph_consumer_aligned_admission": {
                    "label": "B6b",
                    "base_ranking": "flat_semantic_rrf",
                    "policy_revision": FIXED_GRAPH_POLICY_REVISION,
                    "profile": "typed_contract",
                    "seed_count": FIXED_GRAPH_SEED_COUNT,
                    "depth": FIXED_GRAPH_DEPTH,
                    "score_combination": "seed_score_or_max_graph_path",
                    "edge_weights": "frozen_intent_relation_weights",
                    "confidence_weights": True,
                    "contract_signals": True,
                    "output_promotion_policy_revision": (CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION),
                    "output_promotion_scope": "required_data_consumers",
                    "candidate_admission_policy_revision": (FIXED_GRAPH_ADMISSION_POLICY_REVISION),
                    "candidate_admission_policy": "consumer_aligned_contract_slot",
                    "candidate_admission_reserved_slots": (FIXED_GRAPH_ADMISSION_RESERVED_SLOTS),
                    "candidate_admission_qualification": (
                        "non_seed_forward_consumer_aligned_api_contract_path_and_"
                        "first_query_action_resource_match"
                    ),
                    "ground_truth_signals": False,
                    "selector_signals": False,
                },
                "graph_budget_aware_schema_admission": {
                    "label": "B6c",
                    "base_ranking": "graph_consumer_aligned_admission",
                    "ranking_changes": False,
                    "schema_projection_policy_revision": (
                        CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION
                    ),
                    "projection_scope": "b6b_evidence_admitted_candidates_only",
                    "projection_payload": [
                        "name",
                        "bounded_semantic_description",
                        "required_parameters",
                    ],
                    "description_char_limit": CONTRACT_PROJECTED_DESCRIPTION_LIMIT,
                    "parameter_description_char_limit": (
                        CONTRACT_PROJECTED_PARAMETER_DESCRIPTION_LIMIT
                    ),
                    "enum_value_limit": CONTRACT_PROJECTED_ENUM_LIMIT,
                    "optional_parameters_included": False,
                    "full_schema_hydration": "before_execution",
                    "ground_truth_signals": False,
                    "selector_signals": False,
                },
                "full_graph_pipeline": {
                    "label": "B7",
                    "base_ranking": "graph_typed_contract",
                    "target_selector": "select_target_candidate:strong_evidence",
                    "producer_expansion": {
                        "max_hops": FIXED_PRODUCER_MAX_HOPS,
                        "max_producers_per_field": FIXED_PRODUCERS_PER_FIELD,
                    },
                    "learning_signals": False,
                    "llm_target": False,
                },
            },
            "ablation_pairs": {
                name: {"from": pair[0], "to": pair[1]} for name, pair in ABLATION_PAIRS.items()
            },
            "producer_edge_diagnostics": {
                "policy_revision": PRODUCER_COVERAGE_POLICY_REVISION,
                "evaluation_scope": "ground_truth_only",
                "graph_profile": "typed_contract",
                "comparison_graph_profile": "consumer_aligned_contract",
                "path_direction": {
                    "retrieval": "both",
                    "dependency": "out",
                },
                "max_depth": FIXED_GRAPH_DEPTH,
                "seed_source": "graph_typed_contract",
                "used_for_ranking": False,
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
        tokenizer={
            "name": context_tokenizer_name,
            "provider": tokenizer_provider,
            "revision": context_tokenizer_revision,
            "library": tokenizer_library,
            "library_version": tokenizer_library_version,
            "add_special_tokens": False,
            "serialization_revision": TOOL_SCHEMA_SERIALIZATION_REVISION,
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
    token_counter: TokenCounter,
    token_budget: int,
    tokenizer_load_ms: float,
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
    started = time.perf_counter()
    untyped_graph, untyped_graph_stats = ingest_openapi_graphify(
        _clone_tools_for_cold_graph(tools),
        promote_contract_signals=False,
        derive_semantic_metadata=True,
    )
    untyped_graph_build_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    typed_graph, typed_graph_stats = ingest_openapi_graphify(
        _clone_tools_for_cold_graph(tools),
        promote_contract_signals=True,
        derive_semantic_metadata=True,
    )
    typed_graph_build_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    consumer_aligned_graph, consumer_aligned_graph_stats = ingest_openapi_graphify(
        _clone_tools_for_cold_graph(tools),
        promote_contract_signals=True,
        contract_signal_options={
            "promote_consumer_aligned_produces": True,
            "max_consumer_aligned_paths_per_field": 1,
        },
        derive_semantic_metadata=True,
    )
    consumer_aligned_graph_build_ms = (time.perf_counter() - started) * 1000
    untyped_graph_retriever = FixedGraphRetriever(
        untyped_graph,
        profile="untyped_topology",
    )
    typed_graph_retriever = FixedGraphRetriever(
        typed_graph,
        profile="typed_contract",
    )
    consumer_aligned_graph_retriever = FixedGraphRetriever(
        consumer_aligned_graph,
        profile="typed_contract",
    )
    consumer_aligned_admission_retriever = FixedGraphRetriever(
        consumer_aligned_graph,
        profile="typed_contract",
        admission_policy="consumer_aligned_contract_slot",
    )
    available_names = {tool.name for tool in tools}
    tools_by_name = {tool.name: tool for tool in tools}
    typed_tools_by_name = dict(typed_graph.tools)
    evaluated: list[dict[str, Any]] = []
    for case in ground_truth_cases:
        rankings: dict[str, list[RankedCandidate]] = {}
        ranking_diagnostics: dict[str, dict[str, Any]] = {}
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
        flat_semantic_full = reciprocal_rank_fusion(
            [flat_semantic_bm25_full, flat_semantic_dense_full],
            top_k=full_ranking_size,
        )
        flat_semantic_fusion_ms = (time.perf_counter() - started) * 1000
        rankings["flat_semantic_rrf"] = flat_semantic_full[:top_k]
        latencies["flat_semantic_rrf"] = (
            flat_semantic_bm25_latency_ms + flat_semantic_dense_latency_ms + flat_semantic_fusion_ms
        )

        started = time.perf_counter()
        untyped_full, ranking_diagnostics["graph_untyped"] = untyped_graph_retriever.rank(
            case["query"],
            flat_semantic_full,
            top_k=full_ranking_size,
        )
        untyped_graph_latency_ms = (time.perf_counter() - started) * 1000
        rankings["graph_untyped"] = untyped_full[:top_k]
        latencies["graph_untyped"] = latencies["flat_semantic_rrf"] + untyped_graph_latency_ms

        started = time.perf_counter()
        typed_full, ranking_diagnostics["graph_typed_contract"] = typed_graph_retriever.rank(
            case["query"],
            flat_semantic_full,
            top_k=full_ranking_size,
        )
        typed_graph_latency_ms = (time.perf_counter() - started) * 1000
        rankings["graph_typed_contract"] = typed_full[:top_k]
        latencies["graph_typed_contract"] = latencies["flat_semantic_rrf"] + typed_graph_latency_ms

        started = time.perf_counter()
        consumer_aligned_full, ranking_diagnostics["graph_consumer_aligned_contract"] = (
            consumer_aligned_graph_retriever.rank(
                case["query"],
                flat_semantic_full,
                top_k=full_ranking_size,
            )
        )
        consumer_aligned_graph_latency_ms = (time.perf_counter() - started) * 1000
        rankings["graph_consumer_aligned_contract"] = consumer_aligned_full[:top_k]
        latencies["graph_consumer_aligned_contract"] = (
            latencies["flat_semantic_rrf"] + consumer_aligned_graph_latency_ms
        )

        started = time.perf_counter()
        (
            rankings["graph_consumer_aligned_admission"],
            ranking_diagnostics["graph_consumer_aligned_admission"],
        ) = consumer_aligned_admission_retriever.rank(
            case["query"],
            flat_semantic_full,
            top_k=top_k,
        )
        consumer_aligned_admission_latency_ms = (time.perf_counter() - started) * 1000
        latencies["graph_consumer_aligned_admission"] = (
            latencies["flat_semantic_rrf"] + consumer_aligned_admission_latency_ms
        )
        rankings["graph_budget_aware_schema_admission"] = list(
            rankings["graph_consumer_aligned_admission"]
        )
        ranking_diagnostics["graph_budget_aware_schema_admission"] = {
            "base_ranking": "graph_consumer_aligned_admission",
            "ranking_unchanged": True,
            "schema_projection_policy_revision": CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION,
        }
        latencies["graph_budget_aware_schema_admission"] = latencies[
            "graph_consumer_aligned_admission"
        ]

        started = time.perf_counter()
        rankings["full_graph_pipeline"], ranking_diagnostics["full_graph_pipeline"] = (
            full_graph_pipeline_rank(
                case["query"],
                typed_full,
                typed_tools_by_name,
                top_k=top_k,
            )
        )
        full_pipeline_latency_ms = (time.perf_counter() - started) * 1000
        latencies["full_graph_pipeline"] = (
            latencies["graph_typed_contract"] + full_pipeline_latency_ms
        )
        producer_edge_coverage = diagnose_required_producer_coverage(
            typed_graph,
            expected_targets=case["expected_targets"],
            required_producers=case.get("required_producers", []),
            seed_names=ranking_diagnostics["graph_typed_contract"]["seeds"],
            max_depth=FIXED_GRAPH_DEPTH,
        )
        producer_edge_coverage_consumer_aligned = diagnose_required_producer_coverage(
            consumer_aligned_graph,
            expected_targets=case["expected_targets"],
            required_producers=case.get("required_producers", []),
            seed_names=ranking_diagnostics["graph_consumer_aligned_contract"]["seeds"],
            max_depth=FIXED_GRAPH_DEPTH,
        )

        observed: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        token_budget_observed: dict[str, Any] = {}
        token_budget_metrics: dict[str, Any] = {}
        for baseline_name, ranking in rankings.items():
            retrieved = [candidate.name for candidate in ranking]
            observed[baseline_name] = {
                "retrieved": retrieved,
                "scores": [
                    {"name": candidate.name, "score": candidate.score} for candidate in ranking
                ],
            }
            if baseline_name in ranking_diagnostics:
                observed[baseline_name]["diagnostics"] = ranking_diagnostics[baseline_name]
            metrics[baseline_name] = _case_metrics(
                retrieved,
                case,
                top_k=top_k,
                tools_by_name=tools_by_name,
                latency_ms=latencies[baseline_name],
            )
            started = time.perf_counter()
            if baseline_name == "graph_budget_aware_schema_admission":
                admission = ranking_diagnostics["graph_consumer_aligned_admission"][
                    "candidate_admission"
                ]
                projection_names = {
                    str(row.get("name") or "")
                    for row in admission.get("admitted") or []
                    if row.get("name")
                }
                budget_selection = apply_contract_projected_token_budget(
                    retrieved,
                    tools_by_name,
                    projection_names=projection_names,
                    token_counter=token_counter,
                    token_budget=token_budget,
                )
            else:
                budget_selection = apply_ranked_token_budget(
                    retrieved,
                    tools_by_name,
                    token_counter=token_counter,
                    token_budget=token_budget,
                )
            token_budget_accounting_ms = (time.perf_counter() - started) * 1000
            selected_names = budget_selection.retrieved
            selected_set = set(selected_names)
            token_budget_observed[baseline_name] = {
                **budget_selection.to_dict(),
                "scores": [
                    {"name": candidate.name, "score": candidate.score}
                    for candidate in ranking
                    if candidate.name in selected_set
                ],
            }
            budget_case_metrics = _case_metrics(
                selected_names,
                case,
                top_k=top_k,
                tools_by_name=tools_by_name,
                latency_ms=latencies[baseline_name],
            )
            budget_case_metrics["schema_chars"] = budget_selection.schema_chars
            budget_case_metrics["schema_utf8_bytes"] = budget_selection.schema_utf8_bytes
            token_budget_metrics[baseline_name] = {
                **budget_case_metrics,
                "schema_tokens": budget_selection.schema_tokens,
                "token_budget_limit": budget_selection.token_budget_limit,
                "token_budget_used": budget_selection.token_budget_used,
                "token_budget_utilization": budget_selection.token_budget_utilization,
                "truncated": float(budget_selection.truncated),
                "token_budget_accounting_ms": token_budget_accounting_ms,
            }

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
                        "context_tokenizer_load": tokenizer_load_ms,
                        "bm25_index_build": bm25.build_latency_ms,
                        "dense_document_encoding": dense.build_latency_ms,
                        "flat_semantic_document_build": flat_semantic_document_build_ms,
                        "flat_semantic_bm25_index_build": flat_semantic_bm25.build_latency_ms,
                        "flat_semantic_dense_document_encoding": (
                            flat_semantic_dense.build_latency_ms
                        ),
                        "untyped_graph_build": untyped_graph_build_ms,
                        "typed_contract_graph_build": typed_graph_build_ms,
                        "consumer_aligned_contract_graph_build": (consumer_aligned_graph_build_ms),
                    },
                    "flat_semantic_coverage": semantic_coverage,
                    "graph_profiles": {
                        "untyped": _graph_profile_summary(untyped_graph_stats),
                        "typed_contract": _graph_profile_summary(typed_graph_stats),
                        "consumer_aligned_contract": _graph_profile_summary(
                            consumer_aligned_graph_stats
                        ),
                    },
                },
                "expected": {
                    "expected_targets": list(case["expected_targets"]),
                    "required_producers": list(case.get("required_producers", [])),
                    "acceptable_alternatives": list(case.get("acceptable_alternatives", [])),
                },
                "observed": observed,
                "metrics": metrics,
                "token_budget_observed": token_budget_observed,
                "token_budget_metrics": token_budget_metrics,
                "diagnostics": {
                    "producer_edge_coverage": producer_edge_coverage,
                    "producer_edge_coverage_consumer_aligned": (
                        producer_edge_coverage_consumer_aligned
                    ),
                },
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
            model_facing_schema(tools_by_name[name]),
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


def _summarize(
    cases: list[dict[str, Any]],
    *,
    seed: int,
    bootstrap_resamples: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    per_baseline = {baseline: _aggregate_metrics(cases, baseline) for baseline in BASELINE_NAMES}
    token_budget_per_baseline = {
        baseline: _aggregate_metrics(cases, baseline, metrics_key="token_budget_metrics")
        for baseline in BASELINE_NAMES
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["context"]["source_id"]].append(case)
    per_source = {
        source_id: {
            baseline: _aggregate_metrics(source_cases, baseline) for baseline in BASELINE_NAMES
        }
        for source_id, source_cases in sorted(grouped.items())
    }
    token_budget_per_source = {
        source_id: {
            baseline: _aggregate_metrics(
                source_cases,
                baseline,
                metrics_key="token_budget_metrics",
            )
            for baseline in BASELINE_NAMES
        }
        for source_id, source_cases in sorted(grouped.items())
    }
    ablations = {
        name: _paired_ablation_summary(cases, before=pair[0], after=pair[1])
        for name, pair in ABLATION_PAIRS.items()
    }
    token_budget_ablations = {
        name: _paired_ablation_summary(
            cases,
            before=pair[0],
            after=pair[1],
            metrics_key="token_budget_metrics",
        )
        for name, pair in ABLATION_PAIRS.items()
    }
    per_source_ablations = {
        source_id: {
            name: _paired_ablation_summary(
                source_cases,
                before=pair[0],
                after=pair[1],
            )
            for name, pair in ABLATION_PAIRS.items()
        }
        for source_id, source_cases in sorted(grouped.items())
    }
    split_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        split_counts[case["context"]["split"]] += 1
    producer_edge_coverage = summarize_producer_edge_coverage(
        [case["diagnostics"]["producer_edge_coverage"] for case in cases]
    )
    producer_edge_coverage_by_source = {
        source_id: summarize_producer_edge_coverage(
            [case["diagnostics"]["producer_edge_coverage"] for case in source_cases]
        )
        for source_id, source_cases in sorted(grouped.items())
    }
    producer_edge_coverage_consumer_aligned = summarize_producer_edge_coverage(
        [case["diagnostics"]["producer_edge_coverage_consumer_aligned"] for case in cases]
    )
    producer_edge_coverage_consumer_aligned_by_source = {
        source_id: summarize_producer_edge_coverage(
            [
                case["diagnostics"]["producer_edge_coverage_consumer_aligned"]
                for case in source_cases
            ]
        )
        for source_id, source_cases in sorted(grouped.items())
    }
    summary = {
        "case_count": len(cases),
        "family_count": len({case["context"]["family_id"] for case in cases}),
        "source_count": len(grouped),
        "split_case_counts": dict(sorted(split_counts.items())),
        "baselines": per_baseline,
        "token_budget_baselines": token_budget_per_baseline,
        "ablations": ablations,
        "token_budget_ablations": token_budget_ablations,
        "per_source": per_source,
        "token_budget_per_source": token_budget_per_source,
        "per_source_ablations": per_source_ablations,
        "producer_edge_coverage": producer_edge_coverage,
        "producer_edge_coverage_by_source": producer_edge_coverage_by_source,
        "producer_edge_coverage_consumer_aligned": (producer_edge_coverage_consumer_aligned),
        "producer_edge_coverage_consumer_aligned_by_source": (
            producer_edge_coverage_consumer_aligned_by_source
        ),
        "setup": {
            "dense_model_load_ms": (
                cases[0]["context"]["baseline_setup_ms"]["dense_model_load"] if cases else 0.0
            ),
            "context_tokenizer_load_ms": (
                cases[0]["context"]["baseline_setup_ms"]["context_tokenizer_load"] if cases else 0.0
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
            "untyped_graph_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"]["untyped_graph_build"]
                for source_id, source_cases in sorted(grouped.items())
            },
            "typed_contract_graph_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "typed_contract_graph_build"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "consumer_aligned_contract_graph_build_ms_by_source": {
                source_id: source_cases[0]["context"]["baseline_setup_ms"][
                    "consumer_aligned_contract_graph_build"
                ]
                for source_id, source_cases in sorted(grouped.items())
            },
            "graph_profiles_by_source": {
                source_id: source_cases[0]["context"]["graph_profiles"]
                for source_id, source_cases in sorted(grouped.items())
            },
        },
    }
    statistics = {
        "bootstrap": {
            baseline: {
                metric: {
                    "confidence": 0.95,
                    "n_resamples": bootstrap_resamples,
                    "mean_ci": list(
                        confidence_interval(
                            _metric_values(cases, baseline, metric),
                            n_bootstrap=bootstrap_resamples,
                            seed=seed,
                        )
                    ),
                }
                for metric in STATISTICAL_METRICS
            }
            for baseline in BASELINE_NAMES
        },
        "token_budget_bootstrap": {
            baseline: {
                metric: {
                    "confidence": 0.95,
                    "n_resamples": bootstrap_resamples,
                    "mean_ci": list(
                        confidence_interval(
                            _metric_values(
                                cases,
                                baseline,
                                metric,
                                metrics_key="token_budget_metrics",
                            ),
                            n_bootstrap=bootstrap_resamples,
                            seed=seed,
                        )
                    ),
                }
                for metric in STATISTICAL_METRICS
            }
            for baseline in BASELINE_NAMES
        },
        "paired_bootstrap": {
            name: _paired_bootstrap(
                cases,
                before=pair[0],
                after=pair[1],
                seed=seed,
                bootstrap_resamples=bootstrap_resamples,
            )
            for name, pair in ABLATION_PAIRS.items()
        },
        "token_budget_paired_bootstrap": {
            name: _paired_bootstrap(
                cases,
                before=pair[0],
                after=pair[1],
                seed=seed,
                metrics_key="token_budget_metrics",
                bootstrap_resamples=bootstrap_resamples,
            )
            for name, pair in ABLATION_PAIRS.items()
        },
    }
    return summary, statistics


def _aggregate_metrics(
    cases: list[dict[str, Any]],
    baseline: str,
    *,
    metrics_key: str = "metrics",
) -> dict[str, float]:
    if not cases:
        return {metric: 0.0 for metric in PRIMARY_METRICS}
    metric_names = (
        *PRIMARY_METRICS,
        "candidate_count",
        "schema_chars",
        "schema_utf8_bytes",
        "latency_ms",
    )
    if metrics_key == "token_budget_metrics":
        metric_names = (
            *metric_names,
            "schema_tokens",
            "token_budget_used",
            "token_budget_utilization",
            "truncated",
            "token_budget_accounting_ms",
        )
    result = {
        metric: fmean(_metric_values(cases, baseline, metric, metrics_key=metrics_key))
        for metric in metric_names
    }
    result["producer_case_count"] = float(
        sum(bool(case["expected"]["required_producers"]) for case in cases)
    )
    return result


def _metric_values(
    cases: list[dict[str, Any]],
    baseline: str,
    metric: str,
    *,
    metrics_key: str = "metrics",
) -> list[float]:
    selected = cases
    if metric == "producer_recall_at_k":
        selected = [case for case in cases if case["expected"]["required_producers"]]
    return [float(case[metrics_key][baseline][metric]) for case in selected] or [0.0]


def _paired_ablation_summary(
    cases: list[dict[str, Any]],
    *,
    before: str,
    after: str,
    metrics_key: str = "metrics",
) -> dict[str, Any]:
    metric_names = list(STATISTICAL_METRICS)
    if metrics_key == "token_budget_metrics":
        metric_names.extend(("schema_tokens", "token_budget_used", "truncated"))
    deltas = {
        metric: _paired_metric_values(
            cases,
            before=before,
            after=after,
            metric=metric,
            metrics_key=metrics_key,
        )
        for metric in metric_names
    }
    return {
        "from": before,
        "to": after,
        "case_count": len(cases),
        "mean_delta": {
            metric: fmean(values) if values else 0.0 for metric, values in deltas.items()
        },
        "improved_case_count": {
            metric: sum(value < 0.0 if metric in _COST_METRICS else value > 0.0 for value in values)
            for metric, values in deltas.items()
        },
        "regressed_case_count": {
            metric: sum(value > 0.0 if metric in _COST_METRICS else value < 0.0 for value in values)
            for metric, values in deltas.items()
        },
        "tied_case_count": {
            metric: sum(value == 0.0 for value in values) for metric, values in deltas.items()
        },
    }


def _paired_bootstrap(
    cases: list[dict[str, Any]],
    *,
    before: str,
    after: str,
    seed: int,
    bootstrap_resamples: int,
    metrics_key: str = "metrics",
) -> dict[str, Any]:
    return {
        metric: {
            "confidence": 0.95,
            "n_resamples": bootstrap_resamples,
            "mean_delta_ci": list(
                confidence_interval(
                    _paired_metric_values(
                        cases,
                        before=before,
                        after=after,
                        metric=metric,
                        metrics_key=metrics_key,
                    ),
                    n_bootstrap=bootstrap_resamples,
                    seed=seed,
                )
            ),
        }
        for metric in STATISTICAL_METRICS
    }


def _paired_metric_values(
    cases: list[dict[str, Any]],
    *,
    before: str,
    after: str,
    metric: str,
    metrics_key: str,
) -> list[float]:
    selected = cases
    if metric == "producer_recall_at_k":
        selected = [case for case in cases if case["expected"]["required_producers"]]
    return [
        float(case[metrics_key][after][metric]) - float(case[metrics_key][before][metric])
        for case in selected
    ] or [0.0]


def _graph_profile_summary(stats: dict[str, Any]) -> dict[str, Any]:
    contract_edges = stats.get("contract_edges")
    if not isinstance(contract_edges, dict):
        contract_edges = {}
    contract_signals = stats.get("contract_signals")
    if not isinstance(contract_signals, dict):
        contract_signals = {}
    contract_edge_count = sum(int(contract_edges.get(key) or 0) for key in ("added", "merged"))
    return {
        "tool_count": int(stats.get("tool_count") or 0),
        "edge_count": int(stats.get("edge_count") or 0),
        "contract_edge_count": contract_edge_count,
        "contract_signals": {
            key: int(contract_signals.get(key) or 0)
            for key in (
                "produces_added",
                "produces_consumer_aligned",
                "produces_skipped",
                "produces_skipped_path_cap",
                "consumes_added",
                "consumes_skipped",
                "required_consumer_demand_keys",
            )
        },
        "by_relation": dict(stats.get("by_relation") or {}),
    }


def _clone_tools_for_cold_graph(tools: list[ToolSchema]) -> list[ToolSchema]:
    clones = copy.deepcopy(tools)
    for tool in clones:
        metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
        ai_metadata = (
            metadata.get("ai_metadata") if isinstance(metadata.get("ai_metadata"), dict) else None
        )
        if ai_metadata is not None:
            ai_metadata.pop("pairs_well_with", None)
        metadata.pop("learning", None)
        metadata.pop("trace_edges", None)
    return clones


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
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    parser.add_argument("--context-tokenizer", default=DEFAULT_CONTEXT_TOKENIZER)
    parser.add_argument(
        "--context-tokenizer-revision",
        default=DEFAULT_CONTEXT_TOKENIZER_REVISION,
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=1000)
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
        token_budget=args.token_budget,
        context_tokenizer_name=args.context_tokenizer,
        context_tokenizer_revision=args.context_tokenizer_revision,
        bootstrap_resamples=args.bootstrap_resamples,
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
                "ablations": artifact.summary["ablations"],
                "producer_edge_coverage": artifact.summary["producer_edge_coverage"],
                "producer_edge_coverage_consumer_aligned": artifact.summary[
                    "producer_edge_coverage_consumer_aligned"
                ],
                "token_budget_metrics": artifact.summary["token_budget_baselines"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
