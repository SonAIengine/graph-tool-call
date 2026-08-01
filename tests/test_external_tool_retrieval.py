import json
import re
from pathlib import Path

from benchmarks.experiment.artifact import validate_artifact
from benchmarks.external_tool_retrieval.toollinkos import (
    TOOLLINKOS_COMMIT,
    _manual_dependency_graph,
    _summarize,
    graph_rag_tool_fusion_rank,
    graph_tool_call_closure_rank,
    load_toollinkos,
    run_toollinkos_parity,
)
from benchmarks.paper_baselines import RankedCandidate


class DeterministicEncoder:
    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [_embedding(text) for text in texts]

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return [_embedding(text) for text in texts]


def _embedding(text: str) -> list[float]:
    values = [0.0] * 16
    for token in re.findall(r"[^\W_]+", text.casefold()):
        values[sum(token.encode()) % len(values)] += 1.0
    return values


def _fixture(root: Path) -> None:
    regular = [
        {
            "name": "book_trip",
            "description": "Book a trip for the user.",
            "parameters": [{"name": "city", "type": "string", "required": True}],
            "depends_on": [
                {
                    "name": "find_city",
                    "dependence_type": "PARAMETER_DIRECTLY_DEPENDS_ON",
                    "parameter_name": "city",
                    "reason": "Resolve a destination.",
                }
            ],
            "func_type": "regular",
        },
        {
            "name": "find_city",
            "description": "Find a destination city.",
            "parameters": [],
            "depends_on": [
                {
                    "name": "get_network",
                    "dependence_type": "TOOL_DIRECTLY_DEPENDS_ON",
                    "reason": "Needs connectivity.",
                }
            ],
            "func_type": "regular",
        },
        {
            "name": "delete_file",
            "description": "Delete a local file.",
            "parameters": [],
            "depends_on": [],
            "func_type": "regular",
        },
    ]
    core = [
        {
            "name": "get_network",
            "description": "Get network connectivity.",
            "parameters": [],
            "depends_on": [],
            "func_type": "core",
        }
    ]
    instances = [
        {
            "user_query": "Book a trip to Seoul",
            "main_golden_function_name": "book_trip",
            "golden_function_names": ["book_trip", "find_city", "get_network"],
        }
    ]
    for name, value in (
        ("regular_tools.json", regular),
        ("core_tools.json", core),
        ("instances.json", instances),
    ):
        (root / name).write_text(json.dumps(value), encoding="utf-8")


def test_graph_rag_tool_fusion_preserves_seed_then_depth_first_dependencies():
    ranking = [RankedCandidate("book_trip", 1.0), RankedCandidate("delete_file", 0.5)]

    result = graph_rag_tool_fusion_rank(
        ranking,
        {
            "book_trip": ["find_city"],
            "find_city": ["get_network"],
            "get_network": [],
            "delete_file": [],
        },
        initial_k=2,
        final_k=4,
    )

    assert [candidate.name for candidate in result] == [
        "book_trip",
        "find_city",
        "get_network",
        "delete_file",
    ]


def test_graph_tool_call_closure_preserves_target_and_completes_dependencies(tmp_path):
    _fixture(tmp_path)
    dataset = load_toollinkos(tmp_path)
    graph = _manual_dependency_graph(dataset)
    seed_ranking = [
        RankedCandidate(name="book_trip", score=1.0),
        RankedCandidate(name="delete_file", score=0.5),
    ]

    ranking, diagnostics = graph_tool_call_closure_rank(
        "book a trip",
        seed_ranking,
        dataset.tools,
        graph,
        initial_k=2,
        final_k=4,
    )

    assert [candidate.name for candidate in ranking] == [
        "book_trip",
        "find_city",
        "get_network",
        "delete_file",
    ]
    assert diagnostics["dependency_closure"]["complete"] is True


def test_load_toollinkos_normalizes_tools_dependencies_and_cases(tmp_path):
    _fixture(tmp_path)

    dataset = load_toollinkos(tmp_path)

    assert len(dataset.tools) == 4
    assert dataset.dependencies["book_trip"] == ["find_city"]
    assert dataset.cases[0]["expected_target"] == "book_trip"
    assert set(dataset.source_hashes) == {
        "regular_tools.json",
        "core_tools.json",
        "instances.json",
    }


def test_toollinkos_typed_graph_distinguishes_direct_and_indirect_dependencies(tmp_path):
    _fixture(tmp_path)
    regular_path = tmp_path / "regular_tools.json"
    rows = json.loads(regular_path.read_text())
    rows[0]["depends_on"].append(
        {
            "name": "delete_file",
            "dependence_type": "TOOL_INDIRECTLY_DEPENDS_ON",
            "reason": "Optional follow-up.",
        }
    )
    regular_path.write_text(json.dumps(rows), encoding="utf-8")

    graph = _manual_dependency_graph(load_toollinkos(tmp_path))
    edges = graph.graph.get_edges_from("book_trip", direction="out")
    relations = {target: attrs["relation"] for _, target, attrs in edges}

    assert str(relations["find_city"].value) == "requires"
    assert str(relations["delete_file"].value) == "complementary"


def test_run_toollinkos_parity_writes_valid_paired_artifact(tmp_path):
    _fixture(tmp_path)
    output = tmp_path / "artifact.json"

    artifact = run_toollinkos_parity(
        tmp_path,
        output_path=output,
        top_k_values=(2, 4),
        initial_k=1,
        dense_encoder=DeterministicEncoder(),
        dense_model_name="deterministic-test-encoder",
        dense_model_revision="v1",
        bootstrap_resamples=25,
        created_at="2026-08-01T00:00:00+00:00",
    )

    assert output.is_file()
    assert validate_artifact(artifact).valid
    assert artifact.dataset["automatic_graph_construction_evaluated"] is False
    assert artifact.dataset["official_commit"] == TOOLLINKOS_COMMIT
    assert artifact.summary["case_count"] == 1
    assert set(artifact.summary["baselines"]) == {
        "bm25",
        "dense",
        "hybrid_rrf",
        "graph_rag_tool_fusion",
        "graph_tool_call_typed",
        "graph_tool_call_closure",
    }
    assert artifact.cases[0]["results"]["graph_rag_tool_fusion"]["recall_at_4"] == 1.0
    role_metrics = artifact.summary["graph_tool_call_closure_role_metrics"]
    assert role_metrics["selected_target_hit"] == 1.0
    assert role_metrics["target_shortlist_hit"] == 1.0
    assert role_metrics["closure_all_required"] == 1.0
    comparison = artifact.statistics["comparisons"]["grtf_minus_hybrid"]["recall_at_2"]
    assert comparison["mean_delta"] >= 0.0


def test_toollinkos_summary_handles_empty_case_set():
    assert _summarize([], (10,)) == {
        "case_count": 0,
        "baselines": {},
        "graph_tool_call_closure_role_metrics": {},
    }
