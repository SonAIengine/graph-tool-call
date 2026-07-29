from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.experiment.artifact import validate_artifact
from benchmarks.paper_baselines import (
    FIXED_BM25_TOKENIZER_REVISION,
    FixedBM25Retriever,
    fixed_lexical_tokens,
    oracle_rank,
    run_paper_baselines,
    seeded_random_rank,
)
from graph_tool_call.core.tool import ToolSchema

MANIFEST = Path("benchmarks/corpus/manifest.json")


@pytest.fixture(scope="module")
def baseline_artifact(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("paper-baselines") / "artifact.json"
    return run_paper_baselines(
        MANIFEST,
        top_k=5,
        seed=17,
        output_path=output,
        created_at="2026-07-29T00:00:00+00:00",
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
    }


def test_all_baselines_share_candidate_count_budget(baseline_artifact):
    top_k = baseline_artifact.config["top_k"]

    for case in baseline_artifact.cases:
        for baseline in ("seeded_random", "oracle", "bm25"):
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


def test_runner_rankings_are_reproducible(baseline_artifact, tmp_path: Path):
    repeated = run_paper_baselines(
        MANIFEST,
        top_k=5,
        seed=17,
        output_path=tmp_path / "repeated.json",
        created_at="2026-07-29T00:00:00+00:00",
    )

    first_rankings = [case["observed"] for case in baseline_artifact.cases]
    repeated_rankings = [case["observed"] for case in repeated.cases]
    assert first_rankings == repeated_rankings
    assert baseline_artifact.summary == repeated.summary


def test_held_out_split_is_blocked_without_explicit_access(tmp_path: Path):
    with pytest.raises(ValueError, match="requires --allow-held-out"):
        run_paper_baselines(
            MANIFEST,
            splits=("test",),
            output_path=tmp_path / "held-out.json",
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
