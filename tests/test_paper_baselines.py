import hashlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.experiment.artifact import validate_artifact
from benchmarks.paper_baselines import (
    CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION,
    FIXED_BM25_TOKENIZER_REVISION,
    FIXED_GRAPH_ADMISSION_POLICY_REVISION,
    FIXED_GRAPH_ADMISSION_RESERVED_SLOTS,
    FIXED_GRAPH_POLICY_REVISION,
    FIXED_RRF_K,
    PRODUCER_COVERAGE_POLICY_REVISION,
    PRODUCER_COVERAGE_REASON_CODES,
    FixedBM25Retriever,
    FixedDenseRetriever,
    FixedGraphRetriever,
    RankedCandidate,
    SentenceTransformerDenseEncoder,
    diagnose_required_producer_coverage,
    fixed_lexical_tokens,
    flat_semantic_coverage,
    flat_semantic_document,
    flat_semantic_metadata,
    full_graph_pipeline_rank,
    oracle_rank,
    reciprocal_rank_fusion,
    run_paper_baselines,
    seeded_random_rank,
    summarize_producer_edge_coverage,
)
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.graphify import CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION
from graph_tool_call.ontology.schema import Confidence, RelationType
from graph_tool_call.tool_graph import ToolGraph

MANIFEST = Path("benchmarks/corpus/manifest.json")


class DeterministicTestEncoder:
    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [_test_embedding(text) for text in texts]

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return [_test_embedding(text) for text in texts]


class DeterministicTestTokenCounter:
    def count(self, text: str) -> int:
        return max(1, (len(text) + 3) // 4)


def _test_embedding(text: str) -> list[float]:
    values = [0.0] * 32
    for token in re.findall(r"[^\W_]+", text.casefold()):
        digest = hashlib.sha256(token.encode()).digest()
        values[int.from_bytes(digest[:2], "big") % len(values)] += 1.0
    return values


def _stable_summary(summary):
    stable = {
        "case_count": summary["case_count"],
        "family_count": summary["family_count"],
        "source_count": summary["source_count"],
        "split_case_counts": summary["split_case_counts"],
        "baselines": {},
        "ablations": _stable_ablations(summary["ablations"]),
        "per_source": {},
        "per_source_ablations": {
            source_id: _stable_ablations(ablations)
            for source_id, ablations in summary["per_source_ablations"].items()
        },
        "token_budget_baselines": {},
        "token_budget_ablations": _stable_ablations(summary["token_budget_ablations"]),
        "token_budget_per_source": {},
        "producer_edge_coverage": summary["producer_edge_coverage"],
        "producer_edge_coverage_by_source": summary["producer_edge_coverage_by_source"],
        "producer_edge_coverage_consumer_aligned": summary[
            "producer_edge_coverage_consumer_aligned"
        ],
        "producer_edge_coverage_consumer_aligned_by_source": summary[
            "producer_edge_coverage_consumer_aligned_by_source"
        ],
    }
    for baseline, metrics in summary["baselines"].items():
        stable["baselines"][baseline] = {
            key: value for key, value in metrics.items() if key != "latency_ms"
        }
    for source_id, baselines in summary["per_source"].items():
        stable["per_source"][source_id] = {
            baseline: {key: value for key, value in metrics.items() if key != "latency_ms"}
            for baseline, metrics in baselines.items()
        }
    for baseline, metrics in summary["token_budget_baselines"].items():
        stable["token_budget_baselines"][baseline] = {
            key: value
            for key, value in metrics.items()
            if key not in {"latency_ms", "token_budget_accounting_ms"}
        }
    for source_id, baselines in summary["token_budget_per_source"].items():
        stable["token_budget_per_source"][source_id] = {
            baseline: {
                key: value
                for key, value in metrics.items()
                if key not in {"latency_ms", "token_budget_accounting_ms"}
            }
            for baseline, metrics in baselines.items()
        }
    return stable


def _stable_ablations(ablations):
    stable = {}
    for name, row in ablations.items():
        stable[name] = {
            key: (
                {metric: value for metric, value in values.items() if metric != "latency_ms"}
                if key
                in {
                    "mean_delta",
                    "improved_case_count",
                    "regressed_case_count",
                    "tied_case_count",
                }
                else values
            )
            for key, values in row.items()
        }
    return stable


class _FakeVector(list):
    def tolist(self) -> list[float]:
        return list(self)


@pytest.fixture(scope="module")
def baseline_artifact(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("paper-baselines") / "artifact.json"
    return run_paper_baselines(
        MANIFEST,
        top_k=5,
        seed=17,
        output_path=output,
        created_at="2026-07-29T00:00:00+00:00",
        dense_encoder=DeterministicTestEncoder(),
        dense_model_name="deterministic-test-encoder",
        dense_model_revision="v1",
        token_counter=DeterministicTestTokenCounter(),
        context_tokenizer_name="deterministic-test-tokenizer",
        context_tokenizer_revision="v1",
        bootstrap_resamples=25,
    )


def test_fixed_bm25_uses_only_frozen_baseline_fields():
    tools = [
        ToolSchema(
            name="alpha",
            description="unrelated",
            metadata={"openapi": {"path": "/secret/path"}},
        ),
        ToolSchema(name="zeta", description="unrelated"),
    ]

    ranking = FixedBM25Retriever(tools).rank("secret path", top_k=2)

    assert FIXED_BM25_TOKENIZER_REVISION == "paper-bm25-lexical-v1"
    assert [candidate.name for candidate in ranking] == ["alpha", "zeta"]
    assert [candidate.score for candidate in ranking] == [0.0, 0.0]


def test_fixed_bm25_ranks_name_summary_and_description():
    tools = [
        ToolSchema(name="getOrder", description="Read one purchase order."),
        ToolSchema(
            name="listMembers",
            description="Return customers.",
            metadata={"ai_metadata": {"one_line_summary": "Search member list"}},
        ),
        ToolSchema(name="deleteOrder", description="Remove a purchase order."),
    ]

    ranking = FixedBM25Retriever(tools).rank("search members", top_k=3)

    assert ranking[0].name == "listMembers"
    assert ranking[0].score > ranking[1].score


def test_flat_semantic_document_adds_only_frozen_metadata_fields():
    tool = ToolSchema(
        name="getOrder",
        description="Read an order.",
        metadata={
            "ai_metadata": {
                "one_line_summary": "Order detail",
                "canonical_action": "read",
                "primary_resource": "order",
                "result_shape": "single",
            },
            "openapi": {"path_module": "orders"},
            "api_contract": {
                "consumes": [{"field_name": "secret_contract_field"}],
            },
            "graph": {"neighbors": ["secret_graph_neighbor"]},
        },
    )

    document = flat_semantic_document(tool)

    assert "canonical_action read" in document
    assert "primary_resource order" in document
    assert "path_module orders" in document
    assert "result_shape single" in document
    assert "secret_contract_field" not in document
    assert "secret_graph_neighbor" not in document


def test_flat_semantic_bm25_disambiguates_with_shape_metadata():
    tools = [
        ToolSchema(
            name="alpha",
            description="Order operation.",
            metadata={
                "ai_metadata": {
                    "canonical_action": "search",
                    "primary_resource": "order",
                    "result_shape": "list",
                }
            },
        ),
        ToolSchema(
            name="zeta",
            description="Order operation.",
            metadata={
                "ai_metadata": {
                    "canonical_action": "read",
                    "primary_resource": "order",
                    "result_shape": "single",
                }
            },
        ),
    ]

    base = FixedBM25Retriever(tools).rank("single order", top_k=2)
    semantic = FixedBM25Retriever(
        tools,
        document_builder=flat_semantic_document,
    ).rank("single order", top_k=2)

    assert base[0].name == "alpha"
    assert semantic[0].name == "zeta"
    assert semantic[0].score > semantic[1].score


def test_flat_semantic_metadata_uses_deterministic_openapi_derivation():
    tool = ToolSchema(
        name="listPets",
        description="List all pets.",
        tags=["pet"],
        metadata={
            "source": "openapi",
            "method": "get",
            "path": "/pets",
            "openapi": {"operation_id": "listPets"},
        },
    )

    semantics = flat_semantic_metadata(tool)

    assert semantics == {
        "canonical_action": "search",
        "primary_resource": "pet",
        "path_module": "pets",
        "result_shape": "list",
    }
    assert "ai_metadata" not in tool.metadata
    assert tool.metadata["openapi"] == {"operation_id": "listPets"}


def test_flat_semantic_coverage_does_not_invent_non_openapi_metadata():
    tools = [
        ToolSchema(
            name="read_file",
            metadata={
                "source": "mcp",
                "ai_metadata": {
                    "canonical_action": "read",
                    "primary_resource": "file",
                    "result_shape": "single",
                },
            },
        ),
        ToolSchema(name="write_file", metadata={"source": "mcp"}),
    ]

    coverage = flat_semantic_coverage(tools)

    assert coverage["tool_count"] == 2
    assert coverage["canonical_action_count"] == 1
    assert coverage["canonical_action_rate"] == 0.5
    assert flat_semantic_metadata(tools[1]) == {
        "canonical_action": "",
        "primary_resource": "",
        "path_module": "",
        "result_shape": "",
    }
    assert flat_semantic_coverage([]) == {
        "tool_count": 0,
        "canonical_action_count": 0,
        "primary_resource_count": 0,
        "path_module_count": 0,
        "result_shape_count": 0,
        "canonical_action_rate": 0.0,
        "primary_resource_rate": 0.0,
        "path_module_rate": 0.0,
        "result_shape_rate": 0.0,
    }


def test_fixed_dense_accepts_the_same_flat_semantic_document_builder():
    class RecordingEncoder(DeterministicTestEncoder):
        documents: list[str] = []

        def encode_documents(self, texts):
            self.documents = list(texts)
            return super().encode_documents(texts)

    encoder = RecordingEncoder()
    tool = ToolSchema(
        name="getOrder",
        metadata={
            "ai_metadata": {
                "canonical_action": "read",
                "primary_resource": "order",
                "result_shape": "single",
            }
        },
    )

    FixedDenseRetriever(
        [tool],
        encoder,
        document_builder=flat_semantic_document,
    )

    assert "result_shape single" in encoder.documents[0]


def test_fixed_tokenizer_splits_identifiers_and_adds_korean_bigrams():
    tokens = fixed_lexical_tokens("getMemberList 회원조회")

    assert tokens[:3] == ["get", "member", "list"]
    assert {"회원조회", "회원", "원조", "조회"}.issubset(tokens)


def test_retrievers_handle_empty_catalog_and_duplicate_names():
    duplicates = [
        ToolSchema(name="same", description="first"),
        ToolSchema(name="same", description="second"),
    ]

    assert FixedBM25Retriever([]).rank("anything", top_k=5) == []
    assert FixedBM25Retriever(duplicates).rank("anything", top_k=5)[0].name == "same"
    assert len(FixedBM25Retriever(duplicates).rank("anything", top_k=5)) == 1


def test_fixed_dense_retriever_uses_cosine_and_stable_ties():
    tools = [
        ToolSchema(name="zetaOrder", description="purchase order"),
        ToolSchema(name="memberList", description="customer members"),
        ToolSchema(name="alphaOrder", description="purchase order"),
    ]

    ranking = FixedDenseRetriever(tools, DeterministicTestEncoder()).rank(
        "purchase order",
        top_k=3,
    )

    assert {candidate.name for candidate in ranking[:2]} == {"alphaOrder", "zetaOrder"}
    assert ranking[0].score >= ranking[1].score >= ranking[2].score


def test_fixed_dense_rejects_invalid_encoder_output():
    class WrongCountEncoder(DeterministicTestEncoder):
        def encode_documents(self, texts):
            return []

    class MixedDimensionEncoder(DeterministicTestEncoder):
        def encode_documents(self, texts):
            return [[1.0], [1.0, 0.0]]

    tools = [ToolSchema(name="one"), ToolSchema(name="two")]
    with pytest.raises(ValueError, match="different number"):
        FixedDenseRetriever(tools, WrongCountEncoder())
    with pytest.raises(ValueError, match="share one dimension"):
        FixedDenseRetriever(tools, MixedDimensionEncoder())


def test_sentence_transformer_encoder_pins_revision_and_e5_prefixes(monkeypatch):
    calls = {}

    class FakeModel:
        def encode(self, texts, **kwargs):
            calls["texts"] = texts
            calls["encode_kwargs"] = kwargs
            return [_FakeVector([1.0, 0.0]) for _ in texts]

    def fake_sentence_transformer(model_name, **kwargs):
        calls["model_name"] = model_name
        calls["model_kwargs"] = kwargs
        return FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=fake_sentence_transformer),
    )
    encoder = SentenceTransformerDenseEncoder(
        model_name="model",
        revision="commit",
        device="cpu",
        batch_size=7,
    )

    assert encoder.encode_documents(["tool document"]) == [[1.0, 0.0]]
    assert calls["texts"] == ["passage: tool document"]
    assert calls["model_kwargs"] == {
        "revision": "commit",
        "device": "cpu",
        "trust_remote_code": False,
    }
    encoder.encode_queries(["user query"])
    assert calls["texts"] == ["query: user query"]
    assert calls["encode_kwargs"]["batch_size"] == 7
    assert calls["encode_kwargs"]["normalize_embeddings"] is True


def test_fixed_rrf_is_unweighted_and_uses_stable_ties():
    lexical = [
        RankedCandidate("alpha", 20.0),
        RankedCandidate("beta", 10.0),
    ]
    dense = [
        RankedCandidate("beta", 0.9),
        RankedCandidate("alpha", 0.8),
    ]

    ranking = reciprocal_rank_fusion([lexical, dense], top_k=2)

    assert FIXED_RRF_K == 60
    assert [candidate.name for candidate in ranking] == ["alpha", "beta"]
    assert ranking[0].score == pytest.approx(ranking[1].score)


def test_b5_untyped_graph_excludes_contract_only_edges():
    tools = [
        ToolSchema(name="target"),
        ToolSchema(name="distractor"),
        ToolSchema(name="producer"),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "target",
        "producer",
        relation=RelationType.REQUIRES,
        confidence=Confidence.EXTRACTED,
        evidence_sources=["api_contract"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor", 0.75),
        RankedCandidate("producer", 0.7),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="untyped_topology",
    ).rank("read target", base, top_k=3)

    assert FIXED_GRAPH_POLICY_REVISION == "paper-graph-rerank-v1"
    assert [candidate.name for candidate in ranking] == [
        "target",
        "distractor",
        "producer",
    ]
    assert diagnostics["contract_edges_used"] == 0


def test_b5_untyped_graph_uses_structural_adjacency_without_edge_labels():
    tools = [
        ToolSchema(name="target"),
        *(ToolSchema(name=f"distractor-{index}") for index in range(1, 5)),
        ToolSchema(name="related"),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "target",
        "related",
        relation=RelationType.CONFLICTS_WITH,
        confidence=Confidence.AMBIGUOUS,
        evidence_sources=["structural"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor-1", 0.75),
        RankedCandidate("distractor-2", 0.74),
        RankedCandidate("distractor-3", 0.73),
        RankedCandidate("distractor-4", 0.4),
        RankedCandidate("related", 0.1),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="untyped_topology",
    ).rank("read target", base, top_k=5)

    assert [candidate.name for candidate in ranking] == [
        "target",
        "distractor-1",
        "distractor-2",
        "distractor-3",
        "related",
    ]
    assert diagnostics["edge_count_used"] == 1
    assert diagnostics["contract_edges_used"] == 0
    assert ranking[-1].score == pytest.approx(2 / 3)


def test_b6_typed_graph_uses_contract_edges_and_confidence():
    tools = [
        ToolSchema(name="target"),
        ToolSchema(name="distractor-1"),
        ToolSchema(name="distractor-2"),
        ToolSchema(name="distractor-3"),
        ToolSchema(name="distractor-4"),
        ToolSchema(name="producer"),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "target",
        "producer",
        relation=RelationType.REQUIRES,
        confidence=Confidence.EXTRACTED,
        evidence_sources=["api_contract"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor-1", 0.75),
        RankedCandidate("distractor-2", 0.74),
        RankedCandidate("distractor-3", 0.73),
        RankedCandidate("distractor-4", 0.4),
        RankedCandidate("producer", 0.1),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="typed_contract",
    ).rank("read target", base, top_k=5)

    assert [candidate.name for candidate in ranking] == [
        "target",
        "distractor-1",
        "distractor-2",
        "distractor-3",
        "producer",
    ]
    assert diagnostics["contract_edges_used"] == 1
    assert diagnostics["expanded_tool_count"] == 1
    assert ranking[-1].score == pytest.approx(0.8 * (2 / 3))


def test_b6b_reserves_one_slot_for_forward_contract_candidate():
    tools = [
        ToolSchema(name="target"),
        *(ToolSchema(name=f"distractor-{index}") for index in range(1, 5)),
        ToolSchema(
            name="producer",
            metadata={
                "ai_metadata": {
                    "canonical_action": "read",
                    "primary_resource": "target",
                    "result_shape": "single",
                },
                "produces": [
                    {
                        "field_name": "id",
                        "json_path": "$.id",
                        "consumer_alignment_only": True,
                        "consumer_alignment": {
                            "policy_revision": CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION,
                            "consumer_tools": ["target"],
                        },
                    }
                ],
            },
        ),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "target",
        "producer",
        relation=RelationType.REQUIRES,
        confidence=Confidence.EXTRACTED,
        evidence_sources=["api_contract"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor-1", 0.9),
        RankedCandidate("distractor-2", 0.8),
        RankedCandidate("distractor-3", 0.7),
        RankedCandidate("distractor-4", 0.6),
        RankedCandidate("producer", 0.1),
    ]

    protected, _ = FixedGraphRetriever(
        graph,
        profile="typed_contract",
    ).rank("read target", base, top_k=5)
    admitted, diagnostics = FixedGraphRetriever(
        graph,
        profile="typed_contract",
        admission_policy="consumer_aligned_contract_slot",
    ).rank("read target", base, top_k=5)

    assert [candidate.name for candidate in protected] == [
        "target",
        "distractor-1",
        "distractor-2",
        "distractor-3",
        "distractor-4",
    ]
    assert [candidate.name for candidate in admitted] == [
        "target",
        "distractor-1",
        "distractor-2",
        "distractor-3",
        "producer",
    ]
    admission = diagnostics["candidate_admission"]
    assert FIXED_GRAPH_ADMISSION_POLICY_REVISION == "paper-consumer-aligned-contract-slot-v1"
    assert FIXED_GRAPH_ADMISSION_RESERVED_SLOTS == 1
    assert admission["triggered"] is True
    assert admission["qualified_candidate_count"] == 1
    assert admission["admitted"] == [
        {
            "name": "producer",
            "score": pytest.approx(0.8 * (2 / 3)),
            "admission_score": pytest.approx(0.8 * (2 / 3)),
            "path": ["target", "producer"],
            "semantic_evidence": [
                {
                    "source": "first_query_action",
                    "value": "read",
                },
                {
                    "source": "resource_terms",
                    "matched_terms": ["target"],
                },
            ],
        }
    ]
    assert admission["evicted"] == [{"name": "distractor-4", "score": pytest.approx(0.6)}]


def test_b6b_does_not_reserve_slot_for_reverse_contract_traversal():
    tools = [
        ToolSchema(name="target"),
        *(ToolSchema(name=f"distractor-{index}") for index in range(1, 5)),
        ToolSchema(name="consumer"),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "consumer",
        "target",
        relation=RelationType.REQUIRES,
        confidence=Confidence.EXTRACTED,
        evidence_sources=["api_contract"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor-1", 0.9),
        RankedCandidate("distractor-2", 0.8),
        RankedCandidate("distractor-3", 0.7),
        RankedCandidate("distractor-4", 0.6),
        RankedCandidate("consumer", 0.1),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="typed_contract",
        admission_policy="consumer_aligned_contract_slot",
    ).rank("read target", base, top_k=5)

    assert [candidate.name for candidate in ranking] == [
        "target",
        "distractor-1",
        "distractor-2",
        "distractor-3",
        "distractor-4",
    ]
    admission = diagnostics["candidate_admission"]
    assert admission["qualified_candidate_count"] == 0
    assert admission["triggered"] is False


def test_b6b_rejects_consumer_aligned_candidate_with_unrelated_semantics():
    tools = [
        ToolSchema(name="target"),
        *(ToolSchema(name=f"distractor-{index}") for index in range(1, 5)),
        ToolSchema(
            name="createUnrelated",
            metadata={
                "ai_metadata": {
                    "canonical_action": "create",
                    "primary_resource": "unrelated",
                },
                "produces": [
                    {
                        "field_name": "id",
                        "json_path": "$.id",
                        "consumer_alignment_only": True,
                        "consumer_alignment": {
                            "policy_revision": CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION,
                            "consumer_tools": ["target"],
                        },
                    }
                ],
            },
        ),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    graph.graph.add_edge(
        "target",
        "createUnrelated",
        relation=RelationType.REQUIRES,
        confidence=Confidence.INFERRED,
        evidence_sources=["api_contract"],
    )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("distractor-1", 0.9),
        RankedCandidate("distractor-2", 0.8),
        RankedCandidate("distractor-3", 0.7),
        RankedCandidate("distractor-4", 0.6),
        RankedCandidate("createUnrelated", 0.1),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="typed_contract",
        admission_policy="consumer_aligned_contract_slot",
    ).rank("read target", base, top_k=5)

    assert [candidate.name for candidate in ranking][-1] == "distractor-4"
    admission = diagnostics["candidate_admission"]
    assert admission["contract_qualified_candidate_count"] == 1
    assert admission["qualified_candidate_count"] == 0
    assert admission["triggered"] is False


def test_fixed_graph_retriever_bounds_cycles_and_keeps_the_strongest_path():
    tools = [
        ToolSchema(name="target"),
        ToolSchema(name="short_path"),
        ToolSchema(name="long_path"),
        ToolSchema(name="result"),
        ToolSchema(name="fallback"),
        ToolSchema(name="tail"),
    ]
    graph = ToolGraph()
    for tool in tools:
        graph.add_tool(tool)
    for source, target in (
        ("target", "short_path"),
        ("short_path", "target"),
        ("short_path", "result"),
        ("target", "long_path"),
        ("long_path", "result"),
    ):
        graph.graph.add_edge(
            source,
            target,
            relation=RelationType.REQUIRES,
            confidence=Confidence.EXTRACTED,
            evidence_sources=["structural"],
        )
    base = [
        RankedCandidate("target", 1.0),
        RankedCandidate("short_path", 0.9),
        RankedCandidate("long_path", 0.8),
        RankedCandidate("fallback", 0.7),
        RankedCandidate("tail", 0.2),
        RankedCandidate("result", 0.1),
    ]

    ranking, diagnostics = FixedGraphRetriever(
        graph,
        profile="untyped_topology",
    ).rank("target result", base, top_k=6)

    assert len({candidate.name for candidate in ranking}) == len(ranking) == 6
    assert diagnostics["depth"] == 2
    assert diagnostics["graph_reached_tool_count"] >= 1
    assert next(candidate for candidate in ranking if candidate.name == "result").score > 0.0


def test_b7_selector_and_producer_expansion_share_the_candidate_budget():
    tools = [
        ToolSchema(
            name="getOrderDetail",
            description="Read one order detail.",
            metadata={
                "ai_metadata": {
                    "canonical_action": "read",
                    "primary_resource": "order",
                    "result_shape": "single",
                },
                "consumes": [
                    {
                        "field_name": "order_id",
                        "semantic_tag": "order_id",
                        "kind": "data",
                        "required": True,
                    }
                ],
            },
        ),
        ToolSchema(
            name="listOrders",
            description="List orders and return order identifiers.",
            metadata={
                "ai_metadata": {
                    "canonical_action": "search",
                    "primary_resource": "order",
                    "result_shape": "list",
                },
                "produces": [
                    {
                        "field_name": "order_id",
                        "semantic_tag": "order_id",
                        "kind": "data",
                    }
                ],
            },
        ),
        ToolSchema(name="unrelated"),
    ]
    typed_ranking = [
        RankedCandidate("getOrderDetail", 1.0),
        RankedCandidate("unrelated", 0.9),
        RankedCandidate("listOrders", 0.2),
    ]

    ranking, diagnostics = full_graph_pipeline_rank(
        "show one order detail",
        typed_ranking,
        {tool.name: tool for tool in tools},
        top_k=2,
    )

    assert [candidate.name for candidate in ranking] == [
        "getOrderDetail",
        "listOrders",
    ]
    assert diagnostics["selected_target"] == "getOrderDetail"
    assert diagnostics["producer_candidates"] == ["listOrders"]
    assert diagnostics["candidate_count"] == 2


def test_b7_handles_an_empty_candidate_surface():
    ranking, diagnostics = full_graph_pipeline_rank(
        "anything",
        [],
        {},
        top_k=5,
    )

    assert ranking == []
    assert diagnostics == {
        "selected_target": "",
        "producer_candidates": [],
        "candidate_count": 0,
        "target_selector": {},
    }


def test_producer_coverage_diagnoses_direct_contract_evidence():
    target = ToolSchema(
        name="getOrder",
        metadata={
            "consumes": [
                {
                    "field_name": "order_id",
                    "semantic_tag": "order_id",
                    "kind": "data",
                    "required": True,
                }
            ]
        },
    )
    producer = ToolSchema(
        name="listOrders",
        metadata={
            "produces": [
                {
                    "field_name": "orderId",
                    "semantic_tag": "order_id",
                    "kind": "data",
                }
            ]
        },
    )
    graph = ToolGraph()
    graph.add_tool(target)
    graph.add_tool(producer)
    graph.graph.add_edge(
        "getOrder",
        "listOrders",
        relation=RelationType.REQUIRES,
        confidence=Confidence.INFERRED,
        conf_score=0.85,
        evidence_sources=["api_contract"],
        data_flow={"to_field": "order_id", "from_field": "orderId"},
    )

    report = diagnose_required_producer_coverage(
        graph,
        expected_targets=["getOrder"],
        required_producers=["listOrders"],
        seed_names=["getOrder"],
        max_depth=2,
    )

    pair = report["pairs"][0]
    assert report["policy_revision"] == PRODUCER_COVERAGE_POLICY_REVISION
    assert report["evaluation_scope"] == "ground_truth_only"
    assert pair["status"] == "direct_contract_edge"
    assert pair["contract_matches"] == [
        {
            "consumer_field": "order_id",
            "producer_field": "orderId",
            "consumer_required": True,
            "rule": "semantic_tag",
        }
    ]
    assert pair["direct_contract_edge"] is True
    assert pair["direct_edge_evidence"]["consumer_field"] == "order_id"
    assert pair["direct_edge_evidence"]["producer_field"] == "orderId"
    assert pair["bounded_forward_contract_path"] is True
    assert pair["producer_reachable_from_seeds"] is True
    assert pair["best_seed_path"] == ["getOrder", "listOrders"]
    assert pair["reason_codes"] == ["producer_not_seeded"]


def test_producer_coverage_flags_promoted_match_that_did_not_become_an_edge():
    graph = ToolGraph()
    graph.add_tool(
        ToolSchema(
            name="target",
            metadata={
                "consumes": [
                    {
                        "field_name": "item_id",
                        "semantic_tag": "item_id",
                        "kind": "data",
                        "required": True,
                    }
                ]
            },
        )
    )
    graph.add_tool(
        ToolSchema(
            name="producer",
            metadata={
                "produces": [
                    {
                        "field_name": "itemId",
                        "semantic_tag": "item_id",
                        "kind": "data",
                    }
                ]
            },
        )
    )

    pair = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["producer"],
        seed_names=["target"],
    )["pairs"][0]

    assert pair["required_contract_field_match"] is True
    assert pair["promoted_required_contract_field_match"] is True
    assert pair["direct_contract_edge"] is False
    assert "promoted_contract_edge_not_selected" in pair["reason_codes"]


def test_producer_coverage_separates_raw_contracts_from_promoted_fields():
    graph = ToolGraph()
    graph.add_tool(
        ToolSchema(
            name="target",
            metadata={
                "api_contract": {
                    "consumes": [
                        {
                            "field_name": "item_id",
                            "semantic_tag": "item_id",
                            "kind": "data",
                            "required": True,
                        }
                    ]
                }
            },
        )
    )
    graph.add_tool(
        ToolSchema(
            name="producer",
            metadata={
                "api_contract": {
                    "produces": [
                        {
                            "field_name": "itemId",
                            "semantic_tag": "item_id",
                            "kind": "data",
                        }
                    ]
                }
            },
        )
    )

    pair = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["producer"],
    )["pairs"][0]

    assert pair["contract_field_match"] is True
    assert pair["promoted_contract_field_match"] is False
    assert set(pair["reason_codes"]) >= {
        "consumer_input_contract_not_promoted",
        "producer_output_contract_not_promoted",
        "matching_contract_fields_not_promoted",
    }


def test_producer_coverage_separates_missing_contract_and_reverse_edge():
    graph = ToolGraph()
    graph.add_tool(
        ToolSchema(
            name="target",
            metadata={
                "consumes": [
                    {
                        "field_name": "entity_id",
                        "semantic_tag": "entity_id",
                        "kind": "data",
                        "required": True,
                    }
                ]
            },
        )
    )
    graph.add_tool(ToolSchema(name="producer"))
    graph.graph.add_edge(
        "producer",
        "target",
        relation=RelationType.PRECEDES,
        confidence=Confidence.INFERRED,
        evidence_sources=["structural"],
    )

    pair = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["producer"],
        seed_names=["target"],
    )["pairs"][0]

    assert pair["status"] == "bounded_graph_path"
    assert pair["producer_output_contract_present"] is False
    assert pair["direct_graph_edge"] is False
    assert pair["reverse_graph_edge"] is True
    assert pair["bounded_graph_path"] is True
    assert pair["bounded_forward_graph_path"] is False
    assert set(pair["reason_codes"]) >= {
        "producer_output_contract_missing",
        "contract_edge_missing",
        "edge_direction_mismatch",
        "path_direction_mismatch",
        "producer_not_seeded",
    }


def test_producer_coverage_distinguishes_paths_beyond_the_frozen_depth():
    graph = ToolGraph()
    for name in ("target", "step-a", "step-b", "producer"):
        graph.add_tool(ToolSchema(name=name))
    for source, target in (
        ("target", "step-a"),
        ("step-a", "step-b"),
        ("step-b", "producer"),
    ):
        graph.graph.add_edge(
            source,
            target,
            relation=RelationType.REQUIRES,
            confidence=Confidence.INFERRED,
            evidence_sources=["structural"],
        )

    pair = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["producer"],
        seed_names=["target"],
        max_depth=2,
    )["pairs"][0]

    assert pair["status"] == "path_outside_budget"
    assert pair["bounded_graph_path"] is False
    assert pair["shortest_path"] == ["target", "step-a", "step-b", "producer"]
    assert pair["shortest_path_depth"] == 3
    assert "graph_path_beyond_budget" in pair["reason_codes"]
    assert "producer_unreachable_from_seeds" in pair["reason_codes"]


def test_producer_coverage_summary_uses_only_stable_reason_codes():
    graph = ToolGraph()
    graph.add_tool(ToolSchema(name="target"))
    graph.add_tool(ToolSchema(name="producer"))
    report = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["producer"],
        seed_names=[],
    )

    summary = summarize_producer_edge_coverage([report, {"pairs": []}])

    assert summary["case_count"] == 1
    assert summary["pair_count"] == 1
    assert summary["status_counts"] == {"uncovered": 1}
    assert set(summary["reason_code_counts"]) <= PRODUCER_COVERAGE_REASON_CODES
    assert summary["coverage"]["direct_contract_edge"] == {"count": 0, "rate": 0.0}


def test_producer_coverage_marks_missing_ground_truth_tools():
    graph = ToolGraph()
    graph.add_tool(ToolSchema(name="target"))

    pair = diagnose_required_producer_coverage(
        graph,
        expected_targets=["target"],
        required_producers=["missing"],
    )["pairs"][0]

    assert pair["status"] == "missing_tool"
    assert pair["reason_codes"] == [
        "consumer_input_contract_missing",
        "producer_tool_missing",
        "target_not_seeded",
    ]


def test_seeded_random_is_case_stable_and_seed_sensitive():
    tools = [ToolSchema(name=f"tool_{index}") for index in range(20)]

    first = seeded_random_rank(
        tools,
        top_k=8,
        seed=17,
        source_id="source-a",
        case_id="case-a",
    )
    repeated = seeded_random_rank(
        list(reversed(tools)),
        top_k=8,
        seed=17,
        source_id="source-a",
        case_id="case-a",
    )
    changed = seeded_random_rank(
        tools,
        top_k=8,
        seed=18,
        source_id="source-a",
        case_id="case-a",
    )

    assert first == repeated
    assert first != changed


def test_oracle_prioritizes_target_then_producer_then_alternative():
    ranking = oracle_rank(
        expected_targets=["target"],
        required_producers=["producer-a", "producer-b"],
        acceptable_alternatives=["alternative"],
        available_names={"target", "producer-a", "producer-b", "alternative"},
        top_k=3,
    )

    assert [(candidate.name, candidate.score) for candidate in ranking] == [
        ("target", 3.0),
        ("producer-a", 2.0),
        ("producer-b", 2.0),
    ]


def test_train_dev_runner_emits_valid_paired_artifact(baseline_artifact):
    report = validate_artifact(baseline_artifact)

    assert report.valid, report.to_dict()
    assert baseline_artifact.dataset["splits"] == ["train", "dev"]
    assert baseline_artifact.dataset["held_out_accessed"] is False
    assert baseline_artifact.summary["case_count"] == 29
    assert baseline_artifact.summary["family_count"] == 5
    assert baseline_artifact.summary["source_count"] == 5
    assert set(baseline_artifact.summary["baselines"]) == {
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
    }
    assert set(baseline_artifact.summary["ablations"]) == {
        "b5_minus_b4_topology",
        "b6_minus_b5_typed_contract",
        "b6a_minus_b6_output_promotion",
        "b6b_minus_b6a_candidate_admission",
        "b6c_minus_b6b_contract_projection",
        "b7_minus_b6_selector_producers",
        "b7_minus_b4_full_pipeline",
    }
    assert baseline_artifact.model["name"] == "deterministic-test-encoder"
    assert baseline_artifact.model["revision"] == "v1"
    assert baseline_artifact.model["provider"] == "injected"
    assert baseline_artifact.tokenizer["name"] == "deterministic-test-tokenizer"
    assert baseline_artifact.tokenizer["revision"] == "v1"
    assert baseline_artifact.tokenizer["provider"] == "injected"
    assert baseline_artifact.summary["setup"]["dense_model_load_ms"] >= 0.0


def test_all_baselines_share_candidate_count_budget(baseline_artifact):
    top_k = baseline_artifact.config["top_k"]

    for case in baseline_artifact.cases:
        for baseline in (
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
        ):
            retrieved = case["observed"][baseline]["retrieved"]
            metrics = case["metrics"][baseline]
            assert len(retrieved) <= top_k
            assert metrics["candidate_count"] == len(retrieved)
            assert set(metrics) >= {
                "target_hit_at_k",
                "producer_recall_at_k",
                "required_tool_recall_at_k",
                "all_required_found_at_k",
                "precision_at_k",
                "mrr",
                "average_precision",
                "ndcg_at_k",
                "schema_chars",
                "schema_utf8_bytes",
                "latency_ms",
            }
            budget_observed = case["token_budget_observed"][baseline]
            budget_metrics = case["token_budget_metrics"][baseline]
            assert budget_observed["retrieved"] == retrieved[: len(budget_observed["retrieved"])]
            assert budget_metrics["candidate_count"] == len(budget_observed["retrieved"])
            assert budget_metrics["schema_tokens"] <= 2048
            assert budget_metrics["token_budget_used"] == budget_metrics["schema_tokens"]
            assert 0.0 <= budget_metrics["token_budget_utilization"] <= 1.0
            assert budget_metrics["truncated"] in {0.0, 1.0}
            assert budget_metrics["token_budget_accounting_ms"] >= 0.0
    assert "latency_ms" in baseline_artifact.summary["baselines"]["dense"]
    assert "schema_tokens" in baseline_artifact.summary["token_budget_baselines"]["dense"]
    assert "latency_ms" in baseline_artifact.statistics["bootstrap"]["hybrid_rrf"]
    assert "latency_ms" in baseline_artifact.statistics["token_budget_bootstrap"]["hybrid_rrf"]
    assert baseline_artifact.config["token_budget"] == {
        "type": "model_facing_schema_tokens",
        "limit": 2048,
        "candidate_limit": 5,
        "policy_revision": "ranked-greedy-whole-schema-v1",
        "alternate_policy_revisions": {
            "graph_budget_aware_schema_admission": ("paper-contract-projected-admission-v1")
        },
        "serialization_revision": "paper-tool-schema-json-v1",
        "add_special_tokens": False,
        "payload_scope": ["name", "description", "parameters"],
        "query_tokens_included": False,
    }
    assert baseline_artifact.config["bootstrap_resamples"] == 25
    assert baseline_artifact.config["baselines"]["flat_semantic_rrf"] == {
        "label": "B4",
        "channels": ["flat_semantic_bm25", "flat_semantic_dense"],
        "fusion": "unweighted_reciprocal_rank_fusion",
        "rrf_k": 60,
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
    }
    assert baseline_artifact.config["baselines"]["graph_untyped"]["label"] == "B5"
    assert baseline_artifact.config["baselines"]["graph_typed_contract"]["label"] == "B6"
    assert (
        baseline_artifact.config["baselines"]["graph_consumer_aligned_contract"]["label"] == "B6a"
    )
    assert (
        baseline_artifact.config["baselines"]["graph_consumer_aligned_contract"][
            "output_promotion_policy_revision"
        ]
        == CONSUMER_ALIGNED_OUTPUT_POLICY_REVISION
    )
    assert (
        baseline_artifact.config["baselines"]["graph_consumer_aligned_contract"][
            "ground_truth_signals"
        ]
        is False
    )
    admission_config = baseline_artifact.config["baselines"]["graph_consumer_aligned_admission"]
    assert admission_config["label"] == "B6b"
    assert (
        admission_config["candidate_admission_policy_revision"]
        == FIXED_GRAPH_ADMISSION_POLICY_REVISION
    )
    assert admission_config["candidate_admission_reserved_slots"] == 1
    assert admission_config["ground_truth_signals"] is False
    for case in baseline_artifact.cases:
        admission = case["observed"]["graph_consumer_aligned_admission"]["diagnostics"][
            "candidate_admission"
        ]
        assert admission["policy_revision"] == FIXED_GRAPH_ADMISSION_POLICY_REVISION
        assert admission["reserved_slots"] == FIXED_GRAPH_ADMISSION_RESERVED_SLOTS
    admission_ablation = baseline_artifact.summary["ablations"]["b6b_minus_b6a_candidate_admission"]
    assert admission_ablation["improved_case_count"]["target_hit_at_k"] >= 1
    assert admission_ablation["improved_case_count"]["producer_recall_at_k"] >= 1
    for metric in (
        "target_hit_at_k",
        "producer_recall_at_k",
        "required_tool_recall_at_k",
        "all_required_found_at_k",
        "precision_at_k",
        "mrr",
        "average_precision",
        "ndcg_at_k",
    ):
        assert admission_ablation["regressed_case_count"][metric] == 0
    assert baseline_artifact.config["baselines"]["full_graph_pipeline"]["label"] == "B7"
    assert baseline_artifact.config["baselines"]["graph_untyped"]["contract_signals"] is False
    assert baseline_artifact.config["baselines"]["graph_typed_contract"]["contract_signals"] is True
    assert baseline_artifact.config["baselines"]["full_graph_pipeline"]["producer_expansion"] == {
        "max_hops": 1,
        "max_producers_per_field": 3,
    }
    assert baseline_artifact.config["producer_edge_diagnostics"] == {
        "policy_revision": PRODUCER_COVERAGE_POLICY_REVISION,
        "evaluation_scope": "ground_truth_only",
        "graph_profile": "typed_contract",
        "comparison_graph_profile": "consumer_aligned_contract",
        "path_direction": {
            "retrieval": "both",
            "dependency": "out",
        },
        "max_depth": 2,
        "seed_source": "graph_typed_contract",
        "used_for_ranking": False,
    }
    producer_coverage = baseline_artifact.summary["producer_edge_coverage"]
    assert producer_coverage["case_count"] == 6
    assert producer_coverage["pair_count"] == 7
    assert producer_coverage["coverage"]["consumer_input_contract_present"]["count"] == 7
    assert producer_coverage["coverage"]["producer_output_contract_present"]["count"] == 4
    assert producer_coverage["coverage"]["consumer_promoted_input_present"]["count"] == 7
    assert producer_coverage["coverage"]["producer_promoted_output_present"]["count"] == 1
    assert producer_coverage["coverage"]["contract_field_match"]["count"] == 4
    assert producer_coverage["coverage"]["required_contract_field_match"]["count"] == 2
    assert producer_coverage["coverage"]["promoted_contract_field_match"]["count"] == 0
    assert producer_coverage["coverage"]["promoted_required_contract_field_match"]["count"] == 0
    assert producer_coverage["coverage"]["direct_contract_edge"]["count"] == 0
    assert producer_coverage["coverage"]["bounded_contract_path"]["count"] == 0
    assert producer_coverage["coverage"]["bounded_forward_contract_path"]["count"] == 0
    assert producer_coverage["coverage"]["bounded_graph_path"]["count"] == 4
    assert producer_coverage["coverage"]["bounded_forward_graph_path"]["count"] == 1
    assert producer_coverage["reason_code_counts"]["producer_output_contract_missing"] == 3
    assert producer_coverage["reason_code_counts"]["producer_output_contract_not_promoted"] == 3
    assert producer_coverage["reason_code_counts"]["matching_contract_fields_not_promoted"] == 4
    assert producer_coverage["reason_code_counts"]["path_direction_mismatch"] == 3
    assert set(producer_coverage["reason_code_counts"]) <= PRODUCER_COVERAGE_REASON_CODES
    assert set(baseline_artifact.summary["producer_edge_coverage_by_source"]) == set(
        baseline_artifact.summary["per_source"]
    )
    aligned_coverage = baseline_artifact.summary["producer_edge_coverage_consumer_aligned"]
    assert aligned_coverage["pair_count"] == producer_coverage["pair_count"]
    assert aligned_coverage["coverage"]["producer_promoted_output_present"]["count"] == 4
    assert aligned_coverage["coverage"]["promoted_contract_field_match"]["count"] == 2
    assert aligned_coverage["coverage"]["promoted_required_contract_field_match"]["count"] == 2
    assert aligned_coverage["coverage"]["direct_contract_edge"]["count"] == 2
    assert aligned_coverage["coverage"]["bounded_forward_contract_path"]["count"] == 2
    assert aligned_coverage["reason_code_counts"]["matching_contract_fields_not_promoted"] == 2
    assert set(
        baseline_artifact.summary["producer_edge_coverage_consumer_aligned_by_source"]
    ) == set(baseline_artifact.summary["per_source"])
    for case in baseline_artifact.cases:
        report = case["diagnostics"]["producer_edge_coverage"]
        aligned_report = case["diagnostics"]["producer_edge_coverage_consumer_aligned"]
        assert report["policy_revision"] == PRODUCER_COVERAGE_POLICY_REVISION
        assert report["evaluation_scope"] == "ground_truth_only"
        assert report["summary"]["pair_count"] == len(report["pairs"])
        assert aligned_report["policy_revision"] == PRODUCER_COVERAGE_POLICY_REVISION
        assert aligned_report["evaluation_scope"] == "ground_truth_only"
        assert aligned_report["summary"]["pair_count"] == len(aligned_report["pairs"])
    assert set(baseline_artifact.statistics["paired_bootstrap"]) == set(
        baseline_artifact.summary["ablations"]
    )
    assert set(baseline_artifact.summary["setup"]["flat_semantic_coverage_by_source"]) == {
        "graphql-commerce-project-fixture",
        "mcp-filesystem-project-fixture",
        "mcp-memory-2025.4.25",
        "openapi-kubernetes-core-v1-ad6c155",
        "openapi-swagger-petstore-1.0.27",
    }
    for setup_key in (
        "bm25_index_build_ms_by_source",
        "dense_document_encoding_ms_by_source",
        "flat_semantic_document_build_ms_by_source",
        "flat_semantic_bm25_index_build_ms_by_source",
        "flat_semantic_dense_document_encoding_ms_by_source",
        "untyped_graph_build_ms_by_source",
        "typed_contract_graph_build_ms_by_source",
        "consumer_aligned_contract_graph_build_ms_by_source",
        "graph_profiles_by_source",
    ):
        assert set(baseline_artifact.summary["setup"][setup_key]) == set(
            baseline_artifact.summary["per_source"]
        )


def test_runner_rankings_are_reproducible(baseline_artifact, tmp_path: Path):
    repeated = run_paper_baselines(
        MANIFEST,
        top_k=5,
        seed=17,
        output_path=tmp_path / "repeated.json",
        created_at="2026-07-29T00:00:00+00:00",
        dense_encoder=DeterministicTestEncoder(),
        dense_model_name="deterministic-test-encoder",
        dense_model_revision="v1",
        token_counter=DeterministicTestTokenCounter(),
        context_tokenizer_name="deterministic-test-tokenizer",
        context_tokenizer_revision="v1",
        bootstrap_resamples=25,
    )

    first_rankings = [case["observed"] for case in baseline_artifact.cases]
    repeated_rankings = [case["observed"] for case in repeated.cases]
    assert first_rankings == repeated_rankings
    first_budget_rankings = [case["token_budget_observed"] for case in baseline_artifact.cases]
    repeated_budget_rankings = [case["token_budget_observed"] for case in repeated.cases]
    assert first_budget_rankings == repeated_budget_rankings
    assert _stable_summary(baseline_artifact.summary) == _stable_summary(repeated.summary)


def test_b6c_preserves_b6b_ranking_and_changes_only_admitted_schema_context(
    baseline_artifact,
):
    config = baseline_artifact.config["baselines"]["graph_budget_aware_schema_admission"]
    assert config["label"] == "B6c"
    assert config["base_ranking"] == "graph_consumer_aligned_admission"
    assert config["schema_projection_policy_revision"] == CONTRACT_PROJECTED_SCHEMA_POLICY_REVISION
    assert config["projection_scope"] == "b6b_evidence_admitted_candidates_only"
    assert config["description_char_limit"] == 240
    assert config["parameter_description_char_limit"] == 160
    assert config["enum_value_limit"] == 16
    assert config["optional_parameters_included"] is False
    assert config["full_schema_hydration"] == "before_execution"
    assert config["ground_truth_signals"] is False

    regressed = 0
    projected_schema_count = 0
    for case in baseline_artifact.cases:
        assert (
            case["observed"]["graph_budget_aware_schema_admission"]["retrieved"]
            == case["observed"]["graph_consumer_aligned_admission"]["retrieved"]
        )
        b6b = case["token_budget_metrics"]["graph_consumer_aligned_admission"]
        b6c = case["token_budget_metrics"]["graph_budget_aware_schema_admission"]
        if b6c["required_tool_recall_at_k"] < b6b["required_tool_recall_at_k"]:
            regressed += 1

        budget = case["token_budget_observed"]["graph_budget_aware_schema_admission"]
        admission = case["observed"]["graph_consumer_aligned_admission"]["diagnostics"][
            "candidate_admission"
        ]
        admitted = {row["name"] for row in admission["admitted"]}
        projected = {
            name for name, mode in budget["schema_modes"].items() if mode == "contract_projected"
        }
        assert projected <= admitted
        projected_schema_count += len(projected)

    assert projected_schema_count >= 1
    assert regressed == 0
    ablation = baseline_artifact.summary["token_budget_ablations"][
        "b6c_minus_b6b_contract_projection"
    ]
    assert ablation["regressed_case_count"]["required_tool_recall_at_k"] == 0


def test_held_out_split_is_blocked_without_explicit_access(tmp_path: Path):
    with pytest.raises(ValueError, match="requires --allow-held-out"):
        run_paper_baselines(
            MANIFEST,
            splits=("test",),
            output_path=tmp_path / "held-out.json",
        )


def test_runner_rejects_invalid_token_budget(tmp_path: Path):
    with pytest.raises(ValueError, match="token_budget must be greater than zero"):
        run_paper_baselines(
            MANIFEST,
            token_budget=0,
            output_path=tmp_path / "invalid-budget.json",
        )


def test_runner_rejects_invalid_bootstrap_resamples(tmp_path: Path):
    with pytest.raises(ValueError, match="bootstrap_resamples must be greater than zero"):
        run_paper_baselines(
            MANIFEST,
            bootstrap_resamples=0,
            output_path=tmp_path / "invalid-bootstrap.json",
        )


def test_held_out_split_remains_blocked_until_paper_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "benchmarks.paper_baselines.run.validate_corpus_manifest",
        lambda *args, **kwargs: SimpleNamespace(integrity_ready=True, paper_ready=False),
    )
    with pytest.raises(ValueError, match="paper-readiness gate"):
        run_paper_baselines(
            MANIFEST,
            splits=("test",),
            output_path=tmp_path / "held-out.json",
            allow_held_out=True,
        )
