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
    _case_local_equivalence_priority_names,
    _classify_failure,
    _cohesive_namespace_candidates,
    _equivalence_adjusted_exact_match,
    _evaluate_official_predictions,
    _evaluate_predictions,
    _failure_tags,
    _messages_for_case,
    _normalize_parameters,
    _prepare_tools_for_model,
    _presented_raw_tools,
    _prioritize_candidate_names,
    _suppress_non_priority_equivalent_names,
    _suppress_subsumed_partial_tools,
    run_model_benchmark,
    write_bfcl_result_files,
)
from benchmarks.xgen_tool_graph.llm_loop import ChatResponse
from graph_tool_call.graphify import build_tool_equivalence_groups


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


def test_prepare_tools_can_prefix_case_local_equivalent_surface_hint():
    tools, _name_map = _prepare_tools_for_model(
        [
            {
                "name": "solve_quadratic",
                "description": "Find roots of a quadratic equation.",
                "parameters": {"type": "dict", "properties": {}, "required": []},
            }
        ],
        preferred_equivalent_names={"solve_quadratic"},
    )

    description = tools[0]["function"]["description"]

    assert description.startswith("Case-local tool surface")
    assert "prefer this exact function name" in description
    assert description.endswith("Find roots of a quadratic equation.")


def test_presented_tools_prefer_case_local_schema_for_duplicate_names():
    first_row = {
        "id": "simple_python_0",
        "function": [
            {
                "name": "calculate_triangle_area",
                "description": "Calculate with optional units.",
                "parameters": {
                    "type": "dict",
                    "properties": {"base": {}, "height": {}, "unit": {}},
                    "required": ["base", "height"],
                },
            }
        ],
    }
    current_row = {
        "id": "simple_python_11",
        "function": [
            {
                "name": "calculate_triangle_area",
                "description": "Calculate with base and height only.",
                "parameters": {
                    "type": "dict",
                    "properties": {"base": {}, "height": {}},
                    "required": ["base", "height"],
                },
            }
        ],
    }
    global_tools = llm_loop._tools_by_name([first_row, current_row])

    raw_tools = _presented_raw_tools(
        ["calculate_triangle_area"],
        question_row=current_row,
        tools_by_name=global_tools,
    )

    properties = raw_tools[0]["parameters"]["properties"]
    assert raw_tools[0]["description"] == "Calculate with base and height only."
    assert set(properties) == {"base", "height"}


def test_case_local_equivalence_priority_names_select_equivalent_case_surface_only():
    question_row = {
        "id": "simple_python_6",
        "function": [
            {
                "name": "solve_quadratic",
                "description": "Find the roots of a quadratic equation.",
                "parameters": {
                    "type": "dict",
                    "properties": {"a": {}, "b": {}, "c": {}},
                    "required": ["a", "b", "c"],
                },
            }
        ],
    }
    global_tools = {
        "solve_quadratic_equation": {
            "name": "solve_quadratic_equation",
            "description": "Function solves the quadratic equation and returns its roots.",
            "parameters": {
                "type": "dict",
                "properties": {"a": {}, "b": {}, "c": {}},
                "required": ["a", "b", "c"],
            },
        },
        "solve_quadratic": {
            "name": "solve_quadratic",
            "description": "Solve a quadratic equation given coefficients.",
            "parameters": {
                "type": "dict",
                "properties": {"a": {}, "b": {}, "c": {}, "root_type": {}},
                "required": ["a", "b", "c"],
            },
        },
        "restaurant_finder": {
            "name": "restaurant_finder",
            "description": "Find restaurants nearby.",
            "parameters": {"type": "dict", "properties": {}, "required": []},
        },
    }

    priority_names = _case_local_equivalence_priority_names(
        ["solve_quadratic_equation", "solve_quadratic", "restaurant_finder"],
        question_row=question_row,
        tools_by_name=global_tools,
    )

    assert priority_names == {"solve_quadratic"}


def test_prioritize_candidate_names_moves_priority_surfaces_to_front():
    assert _prioritize_candidate_names(
        ["solve_quadratic_equation", "algebra.quadratic_roots", "solve_quadratic"],
        {"solve_quadratic"},
    ) == ["solve_quadratic", "solve_quadratic_equation", "algebra.quadratic_roots"]


def test_suppress_non_priority_equivalent_names_keeps_case_surface_only():
    question_row = {
        "id": "simple_python_19",
        "function": [
            {
                "name": "math.gcd",
                "description": "Compute the greatest common divisor of two numbers.",
                "parameters": {
                    "type": "dict",
                    "properties": {"num1": {}, "num2": {}},
                    "required": ["num1", "num2"],
                },
            }
        ],
    }
    tools_by_name = {
        "math.gcd": question_row["function"][0],
        "number_theory.gcd": {
            "name": "number_theory.gcd",
            "description": "Compute the greatest common divisor of two given integers.",
            "parameters": {
                "type": "dict",
                "properties": {"number1": {}, "number2": {}},
                "required": ["number1", "number2"],
            },
        },
        "math.hcf": {
            "name": "math.hcf",
            "description": "Calculate the highest common factor of two numbers.",
            "parameters": {
                "type": "dict",
                "properties": {"number1": {}, "number2": {}},
                "required": ["number1", "number2"],
            },
        },
        "calculate_average": {
            "name": "calculate_average",
            "description": "Calculates the average of a list of numbers.",
            "parameters": {"type": "dict", "properties": {}, "required": []},
        },
    }

    names = _suppress_non_priority_equivalent_names(
        ["math.gcd", "number_theory.gcd", "calculate_average", "math.hcf"],
        {"math.gcd"},
        question_row=question_row,
        tools_by_name=tools_by_name,
    )

    assert names == ["math.gcd", "calculate_average"]


def test_suppress_subsumed_partial_tools_hides_sequence_only_helper():
    question_row = {
        "id": "parallel_3",
        "function": [
            {
                "name": "protein_info.get_sequence_and_3D",
                "description": "Retrive the sequence and 3D models of proteins.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "protein_name": {
                            "type": "string",
                            "description": "The name of the protein.",
                        },
                        "model_3d": {
                            "type": "boolean",
                            "description": "Set true to get 3D model of the protein.",
                        },
                    },
                    "required": ["protein_name"],
                },
            }
        ],
    }
    tools_by_name = {
        "protein_info.get_sequence_and_3D": question_row["function"][0],
        "get_protein_sequence": {
            "name": "get_protein_sequence",
            "description": "Retrieve the protein sequence encoded by a human gene.",
            "parameters": {
                "type": "dict",
                "properties": {
                    "gene": {
                        "type": "string",
                        "description": "The human gene of interest.",
                    },
                    "species": {
                        "type": "string",
                        "description": "The species for which the gene is to be analyzed.",
                    },
                },
                "required": ["gene"],
            },
        },
        "fetch_DNA_sequence": {
            "name": "fetch_DNA_sequence",
            "description": "Retrieve the sequence of a DNA molecule from a public database.",
            "parameters": {"type": "dict", "properties": {}, "required": []},
        },
    }

    names = _suppress_subsumed_partial_tools(
        [
            "protein_info.get_sequence_and_3D",
            "get_protein_sequence",
            "fetch_DNA_sequence",
        ],
        query=(
            "Get the protein sequence of human HbA1c, normal hemoglobin, and rat hemoglobin "
            "and their 3D models"
        ),
        question_row=question_row,
        tools_by_name=tools_by_name,
    )

    assert names == ["protein_info.get_sequence_and_3D", "fetch_DNA_sequence"]


def test_normalized_parameters_add_argument_value_preservation_hints():
    schema = _normalize_parameters(
        {
            "type": "dict",
            "properties": {
                "formatted": {
                    "type": "boolean",
                    "description": "Return formatted string if true. Default is true.",
                },
                "interest_rate": {
                    "type": "float",
                    "description": "The annual interest rate.",
                },
                "depreciation_rate": {
                    "type": "integer",
                    "description": "The annual depreciation rate in percentage.",
                },
                "gradeDict": {
                    "type": "dict",
                    "description": "Subject score mapping.",
                },
                "x": {
                    "type": "array",
                    "items": {"type": "float"},
                    "description": "Array of the predictor variable.",
                },
                "return_residuals": {
                    "type": "boolean",
                    "description": "Return residuals.",
                    "default": "false",
                },
            },
            "required": ["formatted", "interest_rate", "gradeDict"],
        },
        query="Fit a model with x=data['sales'] and y=data['future_sales'].",
    )

    properties = schema["properties"]

    assert "pass true" in properties["formatted"]["description"]
    assert "does not explicitly request false" in properties["formatted"]["description"]
    assert "pass the decimal fraction 0.04" in properties["interest_rate"]["description"]
    assert "pass the decimal fraction" not in properties["depreciation_rate"]["description"]
    assert "Pass a JSON object" in properties["gradeDict"]["description"]
    assert "not as top-level arguments" in properties["gradeDict"]["description"]
    assert properties["gradeDict"]["additionalProperties"] is True
    assert properties["x"]["type"] == "string"
    assert "items" not in properties["x"]
    assert "data['sales']" in properties["x"]["description"]
    assert "pass exactly the string" in properties["x"]["description"]
    assert "pass false" in properties["return_residuals"]["description"]
    assert schema["required"] == ["formatted", "interest_rate", "gradeDict"]


def test_messages_can_include_candidate_selection_guidance():
    plain = _messages_for_case("calculate area")
    guided = _messages_for_case("calculate area", candidate_selection_guidance=True)

    assert "Use only argument keys declared" in plain[0]["content"]
    assert "never invent extra argument names" in plain[0]["content"]
    assert "do not flatten them into top-level arguments" in plain[0]["content"]
    assert "Preserve symbolic data references" in plain[0]["content"]
    assert "one tool call per distinct set" in plain[0]["content"]
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


def test_cohesive_namespace_candidates_do_not_drop_undesignaled_namespace_matches():
    names = [
        "calculate_magnetic_field",
        "calculate_voltage_difference",
        "calculate_electric_field_strength",
        "physics.electric_field",
        "physics.magnetic_field",
    ]

    compressed = _cohesive_namespace_candidates(
        names,
        query="Calculate magnetic field and calculate voltage difference",
        enabled=True,
    )

    assert compressed == names


def test_cohesive_namespace_candidates_preserve_signaled_singleton_namespaces():
    names = [
        "vegan_restaurant.find_nearby",
        "restaurant.find",
        "restaurant.search",
        "flight.search",
        "doctor.search",
    ]

    compressed = _cohesive_namespace_candidates(
        names,
        query="Find restaurants and also find flights",
        enabled=True,
    )

    assert compressed == ["restaurant.find", "restaurant.search", "flight.search"]


def test_near_duplicate_tool_surface_tags_candidate_ambiguity():
    tools_by_name = {
        "solve_quadratic": {
            "name": "solve_quadratic",
            "description": "Find the roots of a quadratic equation. Returns both roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"description": "Coefficient of x squared"},
                    "b": {"description": "Coefficient of x"},
                    "c": {"description": "Constant term"},
                },
                "required": ["a", "b", "c"],
            },
        },
        "solve_quadratic_equation": {
            "name": "solve_quadratic_equation",
            "description": "Function solves the quadratic equation and returns its roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"description": "Coefficient of x squared"},
                    "b": {"description": "Coefficient of x"},
                    "c": {"description": "Constant term"},
                },
                "required": ["a", "b", "c"],
            },
        },
        "restaurant_finder": {
            "name": "restaurant_finder",
            "description": "Locate restaurants based on cuisine and city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {}, "cuisine": {}},
                "required": ["city", "cuisine"],
            },
        },
    }

    groups = build_tool_equivalence_groups(list(tools_by_name), tools_by_name)
    assert [group["members"] for group in groups] == [
        ["solve_quadratic", "solve_quadratic_equation"]
    ]
    assert _failure_tags(
        expected_calls=[ExpectedToolCall("solve_quadratic", {"a": [2]})],
        predicted_calls=[PredictedToolCall("solve_quadratic_equation", {"a": 2})],
        tools_by_name=tools_by_name,
        failure_category="candidate_ambiguity",
    ) == ["near_duplicate_tool_surface"]


def test_equivalence_adjusted_exact_match_accepts_equivalent_surface_with_values():
    tools_by_name = {
        "number_theory.gcd": {
            "name": "number_theory.gcd",
            "description": "Compute the greatest common divisor of two given integers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "number1": {"description": "The first integer."},
                    "number2": {"description": "The second integer."},
                },
                "required": ["number1", "number2"],
            },
        },
        "math.gcd": {
            "name": "math.gcd",
            "description": "Calculate the greatest common divisor of the two integers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "num1": {"description": "The first number."},
                    "num2": {"description": "The second number."},
                },
                "required": ["num1", "num2"],
            },
        },
        "math.hypot": {
            "name": "math.hypot",
            "description": "Calculate a hypotenuse.",
            "parameters": {
                "type": "object",
                "properties": {"x": {}, "y": {}},
                "required": ["x", "y"],
            },
        },
    }

    expected = [
        ExpectedToolCall("number_theory.gcd", {"number1": [36], "number2": [48]}),
    ]

    assert (
        _equivalence_adjusted_exact_match(
            expected,
            [PredictedToolCall("math.gcd", {"num1": 36, "num2": 48})],
            tools_by_name=tools_by_name,
            category="simple_python",
            strict_exact_match=0.0,
        )
        == 1.0
    )
    assert (
        _equivalence_adjusted_exact_match(
            expected,
            [PredictedToolCall("math.gcd", {"num1": 36, "num2": 49})],
            tools_by_name=tools_by_name,
            category="simple_python",
            strict_exact_match=0.0,
        )
        == 0.0
    )
    assert (
        _equivalence_adjusted_exact_match(
            expected,
            [PredictedToolCall("math.hypot", {"x": 36, "y": 48})],
            tools_by_name=tools_by_name,
            category="simple_python",
            strict_exact_match=0.0,
        )
        == 0.0
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


def test_prediction_matcher_accepts_nested_possible_value_dicts():
    expected = [
        ExpectedToolCall(
            name="realestate.find_properties",
            arguments={
                "location": ["SD", "San Diego", "San Diego, CA", "CA"],
                "propertyType": ["villa"],
                "bedrooms": [3],
                "budget": [{"min": [300000], "max": [400000]}],
            },
        )
    ]
    predicted = [
        PredictedToolCall(
            name="realestate.find_properties",
            arguments={
                "location": "San Diego, CA",
                "propertyType": "villa",
                "bedrooms": 3,
                "budget": {"min": 300000, "max": 400000},
            },
        )
    ]
    wrong_nested_value = [
        PredictedToolCall(
            name="realestate.find_properties",
            arguments={
                "location": "San Diego, CA",
                "propertyType": "villa",
                "bedrooms": 3,
                "budget": {"min": 300000, "max": 450000},
            },
        )
    ]

    result = _evaluate_predictions(expected, predicted, category="multiple")
    wrong = _evaluate_predictions(expected, wrong_nested_value, category="multiple")

    assert result["argument_value_exact_match"] == 1.0
    assert result["strict_exact_match"] == 1.0
    assert wrong["argument_value_exact_match"] == 0.0
    assert wrong["strict_exact_match"] == 0.0


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


def test_argument_value_failure_tags_identify_actionable_patterns():
    expected = [
        ExpectedToolCall(name="calculate_triangle_area", arguments={"base": [10], "height": [5]}),
        ExpectedToolCall(
            name="get_prime_factors", arguments={"number": [450], "formatted": [True, ""]}
        ),
        ExpectedToolCall(
            name="calculate_average",
            arguments={
                "gradeDict": [{"math": [90], "science": [75], "history": [82], "music": [89]}]
            },
        ),
        ExpectedToolCall(
            name="calculate_mortgage_payment",
            arguments={"loan_amount": [400000], "interest_rate": [0.04], "loan_term": [30]},
        ),
        ExpectedToolCall(
            name="linear_regression_fit",
            arguments={
                "x": ["data['sales']"],
                "y": ["data['future_sales']"],
                "return_residuals": [True],
            },
        ),
    ]
    predicted = [
        PredictedToolCall(
            name="calculate_triangle_area",
            arguments={"base": 10, "height": 5, "unit": "units"},
        ),
        PredictedToolCall(
            name="get_prime_factors",
            arguments={"number": 450, "formatted": False},
        ),
        PredictedToolCall(name="calculate_average", arguments={"gradeDict": ""}),
        PredictedToolCall(
            name="calculate_mortgage_payment",
            arguments={"loan_amount": 400000, "interest_rate": 4, "loan_term": 30},
        ),
        PredictedToolCall(
            name="linear_regression_fit",
            arguments={"x": [100, 200], "y": [110, 220], "return_residuals": True},
        ),
    ]

    tags = _failure_tags(
        expected_calls=expected,
        predicted_calls=predicted,
        tools_by_name={},
        failure_category="argument_value_mismatch",
    )

    assert tags == [
        "unexpected_argument",
        "optional_value_mismatch",
        "structured_value_missing",
        "percentage_scale_mismatch",
        "data_reference_substitution",
    ]


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
    assert report["summary"]["equivalence_adjusted_exact_match"] == 1.0
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
                        "equivalence_adjusted_exact_match": 1.0,
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
    assert row["graph_tool_call"]["equivalence_adjusted_exact_match"] == 1.0


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
