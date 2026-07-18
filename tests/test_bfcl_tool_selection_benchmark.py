from __future__ import annotations

import json
from pathlib import Path

from benchmarks.bfcl_tool_selection.run import (
    _expected_argument_names,
    _expected_tool_names,
    run_benchmark,
)


def test_expected_tool_and_argument_extraction():
    answer = {
        "ground_truth": [
            {"math.add": {"x": [1], "y": [2]}},
            {"calendar.create_event": {"title": ["demo"], "start": ["tomorrow"]}},
        ]
    }

    assert _expected_tool_names(answer) == {"math.add", "calendar.create_event"}
    assert _expected_argument_names(answer) == {
        "math.add": {"x", "y"},
        "calendar.create_event": {"title", "start"},
    }


def test_bfcl_tool_selection_runs_against_local_jsonl_fixture(tmp_path: Path):
    data_root = tmp_path
    answer_root = data_root / "possible_answer"
    answer_root.mkdir()
    _write_jsonl(
        data_root / "BFCL_v4_simple_python.json",
        [
            {
                "id": "simple_python_0",
                "question": [
                    [
                        {
                            "role": "user",
                            "content": "Find the area of a triangle with base 10 and height 5.",
                        }
                    ]
                ],
                "function": [
                    {
                        "name": "calculate_triangle_area",
                        "description": "Calculate the area of a triangle from base and height.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "base": {"type": "integer", "description": "Triangle base."},
                                "height": {"type": "integer", "description": "Triangle height."},
                            },
                            "required": ["base", "height"],
                        },
                    },
                    {
                        "name": "calculate_circle_area",
                        "description": "Calculate the area of a circle from its radius.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "radius": {"type": "number", "description": "Circle radius."}
                            },
                            "required": ["radius"],
                        },
                    },
                ],
            },
            {
                "id": "simple_python_1",
                "question": [
                    [
                        {
                            "role": "user",
                            "content": "Translate hello into Spanish.",
                        }
                    ]
                ],
                "function": [
                    {
                        "name": "translate_text",
                        "description": "Translate text from one language to another language.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "text": {"type": "string", "description": "Text to translate."},
                                "target_language": {
                                    "type": "string",
                                    "description": "Language to translate into.",
                                },
                            },
                            "required": ["text", "target_language"],
                        },
                    },
                    {
                        "name": "summarize_text",
                        "description": "Summarize a long text passage.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "text": {"type": "string", "description": "Text to summarize."}
                            },
                            "required": ["text"],
                        },
                    },
                ],
            },
        ],
    )
    _write_jsonl(
        answer_root / "BFCL_v4_simple_python.json",
        [
            {
                "id": "simple_python_0",
                "ground_truth": [{"calculate_triangle_area": {"base": [10], "height": [5]}}],
            },
            {
                "id": "simple_python_1",
                "ground_truth": [
                    {
                        "translate_text": {
                            "text": ["hello"],
                            "target_language": ["Spanish"],
                        }
                    }
                ],
            },
        ],
    )

    report = run_benchmark(
        categories=["simple_python"],
        data_root=data_root,
        top_k=2,
        min_recall_at_5=1.0,
    )

    assert report["summary"]["status"] == "pass"
    assert report["summary"]["recall_at_5"] == 1.0
    assert report["summary"]["argument_schema_coverage"] == 1.0
    assert report["categories"][0]["corpus_tool_count"] == 4

    limited = run_benchmark(
        categories=["simple_python"],
        data_root=data_root,
        top_k=2,
        limit=1,
    )

    assert limited["categories"][0]["case_count"] == 1
    assert limited["categories"][0]["corpus_tool_count"] == 4


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
