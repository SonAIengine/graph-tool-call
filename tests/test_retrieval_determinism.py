from __future__ import annotations

from graph_tool_call import ToolGraph
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.retrieval.graph_search import GraphSearcher
from graph_tool_call.retrieval.ranking import stable_score_items


def test_stable_score_items_uses_name_for_equal_scores():
    forward = {"toolZulu": 1.0, "toolAlpha": 1.0, "toolMiddle": 1.0}
    reverse = dict(reversed(list(forward.items())))

    assert stable_score_items(forward) == stable_score_items(reverse)
    assert [name for name, _score in stable_score_items(forward)] == [
        "toolAlpha",
        "toolMiddle",
        "toolZulu",
    ]


def _category_graph(names: list[str]) -> ToolGraph:
    graph = ToolGraph()
    for name in names:
        graph.add_tool(
            ToolSchema(
                name=name,
                description="List event records",
                domain="events",
                tags=["events", "list"],
            )
        )
        graph._builder.assign_category(name, "events")
    return graph


def test_resource_search_ties_ignore_tool_insertion_order():
    names = [f"listEvent{i:03d}" for i in range(40)]
    forward = _category_graph(names)
    reverse = _category_graph(list(reversed(names)))

    forward_rank = list(
        GraphSearcher(forward._graph).resource_first_search(
            "events", max_results=8, tools=forward.tools
        )
    )
    reverse_rank = list(
        GraphSearcher(reverse._graph).resource_first_search(
            "events", max_results=8, tools=reverse.tools
        )
    )

    assert forward_rank == reverse_rank
    assert forward_rank == sorted(names)[:8]
