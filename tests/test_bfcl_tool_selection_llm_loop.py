from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

from benchmarks.bfcl_tool_selection import llm_loop
from benchmarks.bfcl_tool_selection.llm_loop import (
    ExpectedToolCall,
    PredictedToolCall,
    _classify_failure,
    _cohesive_namespace_candidates,
    _evaluate_official_predictions,
    _evaluate_predictions,
    _messages_for_case,
    _prepare_tools_for_model,
    run_model_benchmark,
    write_bfcl_result_files,
)
from benchmarks.xgen_tool_graph.llm_loop import ChatResponse


def test_safe_tool_name_round_trip_for_dotted_bfcl_names():
    tools, name_map = _prepare_tools_for_model(
        [
            {
                "name": "triangle_properties.get",
                "description": "Get triangle dimensions.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "side1": {"type": "integer"},
                        "side2": {"type": "integer"},
                    },
                    "required": ["side1", "side2"],
                },
            }
        ]
    )

    safe_name = tools[0]["function"]["name"]

    assert safe_name == "triangle_properties_get"
    assert name_map[safe_name] == "triangle_properties.get"
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_prepare_tools_can_prefix_retrieval_rank_hints():
    tools, _name_map = _prepare_tools_for_model(
        [
            {
                "name": "circle.calculate_area",
                "description": "Calculate area of a circle.",
                "parameters": {"type": "dict", "properties": {}, "required": []},
            }
        ],
        rank_hints=True,
        rank_by_name={"circle.calculate_area": 4},
    )

    description = tools[0]["function"]["description"]

    assert description.startswith("Graph retrieval rank #4")
    assert "Prefer lower rank numbers" in description
    assert description.endswith("Calculate area of a circle.")


def test_messages_can_include_candidate_selection_guidance():
    plain = _messages_for_case("calculate area")
    guided = _messages_for_case("calculate area", candidate_selection_guidance=True)

    assert "Candidate selection guidance" not in plain[0]["content"]
    assert "Candidate selection guidance" in guided[0]["content"]
    assert "same namespace or API family" in guided[0]["content"]


def test_cohesive_namespace_candidates_only_compress_multi_intent_sibling_sets():
    names = [
        "circle.calculate_circumference",
        "area_circle.calculate",
        "math.circle_area",
        "circle.calculate_area",
        "circle_properties.get",
    ]

    compressed = _cohesive_namespace_candidates(
        names,
        query="Find area and also calculate circumference of a circle",
        enabled=True,
    )
    single_intent = _cohesive_namespace_candidates(
        names,
        query="Find area of a circle",
        enabled=True,
    )

    assert compressed == ["circle.calculate_circumference", "circle.calculate_area"]
    assert single_intent == names
    assert (
        _cohesive_namespace_candidates(names, query="area and circumference", enabled=False)
        == names
    )


def test_prediction_matcher_allows_optional_missing_and_parallel_order():
    expected = [
        ExpectedToolCall(
            name="spotify.play",
            arguments={"artist": ["Taylor Swift"], "duration": [20], "unit": ["minutes", ""]},
        ),
        ExpectedToolCall(
            name="spotify.play",
            arguments={"artist": ["Maroon 5"], "duration": [15], "unit": ["minutes", ""]},
        ),
    ]
    predicted = [
        PredictedToolCall(name="spotify.play", arguments={"artist": "Maroon 5", "duration": 15}),
        PredictedToolCall(
            name="spotify.play", arguments={"artist": "Taylor Swift", "duration": 20}
        ),
    ]

    result = _evaluate_predictions(expected, predicted, category="parallel")

    assert result["function_name_exact_match"] == 1.0
    assert result["argument_name_coverage"] == 1.0
    assert result["argument_value_exact_match"] == 1.0
    assert result["strict_exact_match"] == 1.0


def test_prediction_matcher_rejects_unexpected_arguments():
    expected = [
        ExpectedToolCall(name="calculate_triangle_area", arguments={"base": [10], "height": [5]})
    ]
    predicted = [
        PredictedToolCall(
            name="calculate_triangle_area",
            arguments={"base": 10, "height": 5, "color": "blue"},
        )
    ]

    result = _evaluate_predictions(expected, predicted, category="simple_python")

    assert result["function_name_exact_match"] == 1.0
    assert result["argument_value_exact_match"] == 0.0
    assert result["strict_exact_match"] == 0.0


def test_failure_taxonomy_separates_retrieval_and_candidate_errors():
    expected = [ExpectedToolCall(name="math.hypot", arguments={"x": [4], "y": [5]})]
    wrong_tool = [PredictedToolCall(name="calculate_area", arguments={"x": 4, "y": 5})]
    match = _evaluate_predictions(expected, wrong_tool, category="simple_python")

    assert (
        _classify_failure(
            expected_calls=expected,
            predicted_calls=wrong_tool,
            retrieved=["calculate_area", "geometry.area_triangle"],
            tools_presented=["calculate_area", "geometry.area_triangle"],
            match=match,
            official={},
            evaluator_exact_match=0.0,
            response_error="",
        )
        == "retrieval_miss"
    )

    assert (
        _classify_failure(
            expected_calls=expected,
            predicted_calls=wrong_tool,
            retrieved=["math.hypot", "calculate_area"],
            tools_presented=["math.hypot", "calculate_area"],
            match=match,
            official={},
            evaluator_exact_match=0.0,
            response_error="",
        )
        == "candidate_ambiguity"
    )


def test_failure_taxonomy_detects_argument_mismatch_after_correct_tool():
    expected = [ExpectedToolCall(name="math.hypot", arguments={"x": [4], "y": [5]})]
    wrong_args = [PredictedToolCall(name="math.hypot", arguments={"x": 4, "y": 6})]
    match = _evaluate_predictions(expected, wrong_args, category="simple_python")

    assert (
        _classify_failure(
            expected_calls=expected,
            predicted_calls=wrong_args,
            retrieved=["math.hypot"],
            tools_presented=["math.hypot"],
            match=match,
            official={},
            evaluator_exact_match=0.0,
            response_error="",
        )
        == "argument_value_mismatch"
    )


def test_model_loop_runs_against_local_fixture_with_fake_tool_calls(
    tmp_path: Path,
    monkeypatch,
):
    data_root = tmp_path
    answer_root = data_root / "possible_answer"
    answer_root.mkdir()
    _write_jsonl(
        data_root / "BFCL_v4_multiple.json",
        [
            {
                "id": "multiple_0",
                "question": [
                    [
                        {
                            "role": "user",
                            "content": (
                                "Can I find triangle properties for sides 5, 4 and 3 units?"
                            ),
                        }
                    ]
                ],
                "function": [
                    {
                        "name": "triangle_properties.get",
                        "description": "Retrieve the dimensions of a triangle from three sides.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "side1": {"type": "integer"},
                                "side2": {"type": "integer"},
                                "side3": {"type": "integer"},
                                "get_area": {"type": "boolean", "default": True},
                            },
                            "required": ["side1", "side2", "side3"],
                        },
                    },
                    {
                        "name": "circle_properties.get",
                        "description": "Retrieve the dimensions of a circle from radius.",
                        "parameters": {
                            "type": "dict",
                            "properties": {"radius": {"type": "number"}},
                            "required": ["radius"],
                        },
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        answer_root / "BFCL_v4_multiple.json",
        [
            {
                "id": "multiple_0",
                "ground_truth": [
                    {
                        "triangle_properties.get": {
                            "side1": [5],
                            "side2": [4],
                            "side3": [3],
                            "get_area": ["", True],
                        }
                    }
                ],
            }
        ],
    )

    chat_calls = []

    def fake_chat(**kwargs):
        chat_calls.append(kwargs)
        safe_name = kwargs["tools"][0]["function"]["name"]
        return ChatResponse(
            tool_calls=[
                {
                    "function": {
                        "name": safe_name,
                        "arguments": json.dumps({"side1": 5, "side2": 4, "side3": 3}),
                    }
                }
            ],
            input_tokens=42,
            output_tokens=7,
        )

    monkeypatch.setattr(llm_loop, "_chat", fake_chat)

    report = run_model_benchmark(
        model="fake",
        llm_url="http://fake/v1",
        categories=["multiple"],
        data_root=data_root,
        top_k=1,
        tool_source="row",
        cache_dir=tmp_path / "cache",
        min_exact_match=1.0,
    )
    cached_report = run_model_benchmark(
        model="fake",
        llm_url="http://fake/v1",
        categories=["multiple"],
        data_root=data_root,
        top_k=1,
        tool_source="row",
        cache_dir=tmp_path / "cache",
        min_exact_match=1.0,
    )
    namespaced_report = run_model_benchmark(
        model="fake",
        llm_url="http://fake/v1",
        categories=["multiple"],
        data_root=data_root,
        top_k=1,
        tool_source="row",
        cache_dir=tmp_path / "cache",
        cache_namespace="repeat-2",
        min_exact_match=1.0,
    )
    timeout_report = run_model_benchmark(
        model="fake",
        llm_url="http://fake/v1",
        categories=["multiple"],
        data_root=data_root,
        top_k=1,
        tool_source="row",
        cache_dir=tmp_path / "cache",
        timeout=7,
        min_exact_match=1.0,
    )

    assert report["summary"]["status"] == "pass"
    assert report["summary"]["retrieval_recall_at_k"] == 1.0
    assert report["summary"]["model_tool_call_rate"] == 1.0
    assert report["summary"]["strict_exact_match"] == 1.0
    assert report["summary"]["failure_breakdown"] == {"pass": 1}
    assert cached_report["summary"]["strict_exact_match"] == 1.0
    assert namespaced_report["cache_namespace"] == "repeat-2"
    assert timeout_report["summary"]["strict_exact_match"] == 1.0
    assert len(chat_calls) == 3
    assert chat_calls[-1]["timeout"] == 7
    assert (
        report["categories"][0]["cases"][0]["predicted_calls"][0]["name"]
        == "triangle_properties.get"
    )


def test_model_loop_concurrency_preserves_case_order_and_reports_progress(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    data_root = tmp_path
    answer_root = data_root / "possible_answer"
    answer_root.mkdir()
    _write_jsonl(
        data_root / "BFCL_v4_multiple.json",
        [
            {
                "id": "multiple_0",
                "question": [[{"role": "user", "content": "first triangle side 3"}]],
                "function": [
                    {
                        "name": "triangle_properties.get",
                        "description": "Retrieve triangle dimensions.",
                        "parameters": {
                            "type": "dict",
                            "properties": {"side1": {"type": "integer"}},
                            "required": ["side1"],
                        },
                    }
                ],
            },
            {
                "id": "multiple_1",
                "question": [[{"role": "user", "content": "second circle radius 2"}]],
                "function": [
                    {
                        "name": "circle_properties.get",
                        "description": "Retrieve circle dimensions.",
                        "parameters": {
                            "type": "dict",
                            "properties": {"radius": {"type": "integer"}},
                            "required": ["radius"],
                        },
                    }
                ],
            },
        ],
    )
    _write_jsonl(
        answer_root / "BFCL_v4_multiple.json",
        [
            {"id": "multiple_0", "ground_truth": [{"triangle_properties.get": {"side1": [3]}}]},
            {"id": "multiple_1", "ground_truth": [{"circle_properties.get": {"radius": [2]}}]},
        ],
    )

    def fake_chat(**kwargs):
        query = kwargs["messages"][-1]["content"]
        if "first" in query:
            time.sleep(0.02)
            arguments = {"side1": 3}
        else:
            arguments = {"radius": 2}
        return ChatResponse(
            tool_calls=[
                {
                    "function": {
                        "name": kwargs["tools"][0]["function"]["name"],
                        "arguments": json.dumps(arguments),
                    }
                }
            ]
        )

    monkeypatch.setattr(llm_loop, "_chat", fake_chat)

    report = run_model_benchmark(
        model="fake",
        llm_url="http://fake/v1",
        categories=["multiple"],
        data_root=data_root,
        top_k=1,
        tool_source="row",
        concurrency=2,
        progress=True,
        progress_every=1,
    )

    cases = report["categories"][0]["cases"]
    assert [case["case_id"] for case in cases] == ["multiple_0", "multiple_1"]
    assert report["concurrency"] == 2
    assert report["summary"]["strict_exact_match"] == 1.0
    progress = capsys.readouterr().err
    assert "[bfcl] multiple row k=1" in progress
    assert "2/2" in progress


def test_ollama_chat_path_uses_ollama_payload(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=180):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {
            "message": {
                "content": "ok",
                "tool_calls": [{"function": {"name": "calculate_area", "arguments": {"base": 10}}}],
            },
            "prompt_eval_count": 11,
            "eval_count": 3,
        }

    monkeypatch.setattr(llm_loop, "_post_json", fake_post_json)

    response = llm_loop._chat(
        model="qwen3:4b",
        llm_url="http://localhost:11434/api/chat",
        messages=[{"role": "user", "content": "area"}],
        tools=[{"type": "function", "function": {"name": "calculate_area"}}],
        tool_choice="required",
        timeout=9,
        disable_thinking=True,
    )

    assert response.content == "ok"
    assert response.tool_calls[0]["function"]["name"] == "calculate_area"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["think"] is False
    assert captured["payload"]["options"]["temperature"] == 0
    assert captured["timeout"] == 9


def test_official_checker_bridge_uses_bfcl_model_name_conversion(monkeypatch):
    captured = {}

    class FakeLanguage:
        PYTHON = "python"

    class FakeModelConfig:
        underscore_to_dot = True

    def fake_ast_checker(
        func_description,
        model_output,
        possible_answer,
        language,
        test_category,
        model_name,
    ):
        captured.update(
            {
                "func_description": func_description,
                "model_output": model_output,
                "possible_answer": possible_answer,
                "language": language,
                "test_category": test_category,
                "model_name": model_name,
            }
        )
        return {"valid": True, "error": [], "error_type": ""}

    _install_fake_bfcl_eval(
        monkeypatch,
        language=FakeLanguage,
        model_config={"qwen3-32b-FC": FakeModelConfig()},
        ast_checker=fake_ast_checker,
    )

    result = _evaluate_official_predictions(
        function_descriptions=[
            {
                "name": "triangle_properties.get",
                "parameters": {"type": "dict", "properties": {}, "required": []},
            }
        ],
        answer_row={
            "ground_truth": [
                {"triangle_properties.get": {"side1": [5], "side2": [4], "side3": [3]}}
            ]
        },
        predicted_calls=[
            PredictedToolCall(
                name="triangle_properties.get",
                arguments={"side1": 5, "side2": 4, "side3": 3},
            )
        ],
        category="multiple",
        official_model_name="qwen3-32b-FC",
    )

    assert result["official_ast_exact_match"] == 1.0
    assert captured["model_output"] == [
        {"triangle_properties_get": {"side1": 5, "side2": 4, "side3": 3}}
    ]
    assert captured["possible_answer"][0]["triangle_properties.get"]["side1"] == [5]
    assert captured["language"] == "python"
    assert captured["test_category"] == "multiple"
    assert captured["model_name"] == "qwen3-32b-FC"


def test_write_bfcl_result_files_uses_official_result_jsonl_shape(tmp_path: Path):
    report = {
        "official_model_name": "qwen3-32b-FC",
        "graph_tool_call_version": "0.test",
        "tool_source": "retrieved",
        "top_k": 5,
        "categories": [
            {
                "category": "multiple",
                "cases": [
                    {
                        "case_id": "multiple_0",
                        "predicted_calls": [
                            {
                                "name": "triangle_properties.get",
                                "arguments": {"side1": 5, "side2": 4, "side3": 3},
                            }
                        ],
                        "input_tokens": 42,
                        "output_tokens": 7,
                        "latency_ms": 1234,
                        "retrieved": ["triangle_properties.get"],
                        "tools_presented": ["triangle_properties.get"],
                        "failure_category": "pass",
                        "evaluator_exact_match": 1.0,
                    }
                ],
            }
        ],
    }

    written = write_bfcl_result_files(report, tmp_path)

    path = tmp_path / "qwen3-32b-FC" / "non_live" / "BFCL_v4_multiple_result.json"
    assert written == [path]
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["id"] == "multiple_0"
    assert row["result"] == [{"triangle_properties_get": '{"side1":5,"side2":4,"side3":3}'}]
    assert row["input_token_count"] == 42
    assert row["output_token_count"] == 7
    assert row["latency"] == 1.234
    assert row["graph_tool_call"]["version"] == "0.test"
    assert row["graph_tool_call"]["tool_source"] == "retrieved"


def test_write_bfcl_result_files_can_emit_decoded_ast_input(tmp_path: Path):
    report = {
        "official_model_name": "qwen3-32b-FC",
        "categories": [
            {
                "category": "multiple",
                "cases": [
                    {
                        "case_id": "multiple_0",
                        "predicted_calls": [
                            {
                                "name": "triangle_properties.get",
                                "arguments": {"side1": 5},
                            }
                        ],
                    }
                ],
            }
        ],
    }

    write_bfcl_result_files(report, tmp_path, argument_format="decoded")

    path = tmp_path / "qwen3-32b-FC" / "non_live" / "BFCL_v4_multiple_result.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["result"] == [{"triangle_properties_get": {"side1": 5}}]


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _install_fake_bfcl_eval(
    monkeypatch,
    *,
    language,
    model_config,
    ast_checker,
):
    bfcl_eval = types.ModuleType("bfcl_eval")
    constants = types.ModuleType("bfcl_eval.constants")
    enums = types.ModuleType("bfcl_eval.constants.enums")
    enums.Language = language
    model_config_mod = types.ModuleType("bfcl_eval.constants.model_config")
    model_config_mod.MODEL_CONFIG_MAPPING = model_config
    eval_checker = types.ModuleType("bfcl_eval.eval_checker")
    ast_eval = types.ModuleType("bfcl_eval.eval_checker.ast_eval")
    ast_checker_mod = types.ModuleType("bfcl_eval.eval_checker.ast_eval.ast_checker")
    ast_checker_mod.ast_checker = ast_checker

    for name, module in {
        "bfcl_eval": bfcl_eval,
        "bfcl_eval.constants": constants,
        "bfcl_eval.constants.enums": enums,
        "bfcl_eval.constants.model_config": model_config_mod,
        "bfcl_eval.eval_checker": eval_checker,
        "bfcl_eval.eval_checker.ast_eval": ast_eval,
        "bfcl_eval.eval_checker.ast_eval.ast_checker": ast_checker_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
