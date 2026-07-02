"""Unit tests for ``graph_tool_call.plan.extraction``.

find_value_paths BFS ranking + extract_produced_entities (produces schema
→ entity dict, keyed by both semantic_tag and field_name).
"""

from __future__ import annotations

from graph_tool_call.plan.extraction import (
    PathCandidate,
    extract_produced_entities,
    find_value_paths,
)

# ---------------------------------------------------------------------------
# find_value_paths
# ---------------------------------------------------------------------------


def test_find_value_paths_exact_key_shallow():
    output = {"body": {"goodsNo": "G1", "name": "shirt"}}
    cands = find_value_paths(output, field_name="goodsNo")
    assert cands
    assert cands[0].value == "G1"
    assert cands[0].path == "body.goodsNo"
    assert cands[0].method == "exact"


def test_find_value_paths_descends_arrays():
    output = {"items": [{"id": "A"}, {"id": "B"}]}
    cands = find_value_paths(output, field_name="id")
    # 첫 배열 원소가 더 얕은 경로 → 먼저 랭크
    assert cands[0].path == "items[0].id"
    assert cands[0].value == "A"
    paths = {c.path for c in cands}
    assert "items[1].id" in paths


def test_find_value_paths_loose_match_ranks_below_exact():
    output = {"ord_no": "L", "nested": {"ordNo": "E"}}
    cands = find_value_paths(output, field_name="ordNo")
    # exact 'ordNo' (loose target 'ordno') 와 loose 'ord_no' 모두 매치.
    # exact 가 loose 보다 우선.
    assert cands[0].method == "exact"
    assert cands[0].value == "E"
    methods = {c.path: c.method for c in cands}
    assert methods.get("ord_no") == "loose"


def test_find_value_paths_empty_for_missing():
    assert find_value_paths({"a": 1}, field_name="zzz") == []
    assert find_value_paths("notacontainer", field_name="x") == []
    assert find_value_paths({"a": 1}, field_name="") == []


def test_find_value_paths_respects_max_candidates():
    output = {"list": [{"k": i} for i in range(10)]}
    cands = find_value_paths(output, field_name="k", max_candidates=3)
    assert len(cands) == 3
    assert all(isinstance(c, PathCandidate) for c in cands)


# ---------------------------------------------------------------------------
# extract_produced_entities
# ---------------------------------------------------------------------------


def test_extract_produced_entities_by_json_path():
    tool_meta = {
        "produces": [
            {
                "field_name": "goodsNo",
                "json_path": "$.body.items[*].goodsNo",
                "semantic_tag": "goods.id",
            },
        ]
    }
    output = {"body": {"items": [{"goodsNo": "G1"}, {"goodsNo": "G2"}]}}
    ents = extract_produced_entities(tool_meta, output)
    # 첫 배열 원소 값이 semantic + field 두 키로 등록
    assert ents["goods.id"] == "G1"
    assert ents["goodsNo"] == "G1"


def test_extract_produced_entities_bfs_fallback_when_shape_differs():
    """envelope 가 벗겨져 json_path 가 안 맞아도 field-name BFS 로 회수."""
    tool_meta = {
        "produces": [
            {"field_name": "aId", "json_path": "$.body.aId", "semantic_tag": "a.id"},
        ]
    }
    # 실제 응답은 body 래퍼가 없음
    output = {"aId": "X1"}
    ents = extract_produced_entities(tool_meta, output)
    assert ents["a.id"] == "X1"
    assert ents["aId"] == "X1"


def test_extract_produced_entities_skips_unlocatable():
    tool_meta = {"produces": [{"field_name": "missing", "json_path": "$.nope"}]}
    ents = extract_produced_entities(tool_meta, {"other": 1})
    assert ents == {}


def test_extract_produced_entities_no_clobber_first_wins():
    tool_meta = {
        "produces": [
            {"field_name": "id", "json_path": "$.first", "semantic_tag": "x.id"},
            {"field_name": "id", "json_path": "$.second", "semantic_tag": "x.id"},
        ]
    }
    ents = extract_produced_entities(tool_meta, {"first": "A", "second": "B"})
    assert ents["id"] == "A", "첫 produce 값이 우선 (no clobber)"
