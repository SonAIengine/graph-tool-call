"""Next-step tool suggestion based on graph relationships."""

from __future__ import annotations

from dataclasses import dataclass

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType, RelationType


@dataclass
class NextToolSuggestion:
    """A suggested next tool with reason."""

    tool: ToolSchema
    reason: str
    relation: str
    weight: float = 1.0


def suggest_next(
    current_tool: str,
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    *,
    history: list[str] | None = None,
    top_k: int = 5,
) -> list[NextToolSuggestion]:
    """Suggest next tools based on graph relationships from the current tool.

    Uses REQUIRES, PRECEDES, and SIMILAR_TO edges to find likely next steps.
    Already-used tools (in history) are deprioritized.

    Parameters
    ----------
    current_tool:
        Name of the tool that was just executed.
    graph:
        The tool graph.
    tools:
        Registered tool schemas.
    history:
        Previously called tool names (to avoid suggesting repeats).
    top_k:
        Maximum suggestions to return.
    """
    if current_tool not in tools or not graph.has_node(current_tool):
        return []

    used = set(history or [])
    suggestions: list[NextToolSuggestion] = []

    seen: set[str] = set()

    # Priority 1: tools that this tool's output enables (outgoing REQUIRES/PRECEDES)
    for neighbor in graph.get_neighbors(current_tool, direction="out"):
        attrs = graph.get_node_attrs(neighbor)
        if attrs.get("node_type") != NodeType.TOOL or neighbor not in tools:
            continue
        edge_attrs = graph.get_edge_attrs(current_tool, neighbor)
        rel = str(edge_attrs.get("relation", ""))
        if rel in (RelationType.REQUIRES, RelationType.PRECEDES):
            weight = 0.5 if neighbor in used else 1.0
            suggestions.append(
                NextToolSuggestion(
                    tool=tools[neighbor],
                    reason=f"{current_tool} → {neighbor} ({rel})",
                    relation=rel,
                    weight=weight,
                )
            )
            seen.add(neighbor)

    # Priority 2: tools that depend on this tool (incoming REQUIRES)
    for neighbor in graph.get_neighbors(current_tool, direction="in"):
        attrs = graph.get_node_attrs(neighbor)
        if attrs.get("node_type") != NodeType.TOOL or neighbor not in tools:
            continue
        if neighbor in seen:
            continue
        edge_attrs = graph.get_edge_attrs(neighbor, current_tool)
        rel = str(edge_attrs.get("relation", ""))
        if rel == RelationType.REQUIRES:
            weight = 0.4 if neighbor in used else 0.8
            suggestions.append(
                NextToolSuggestion(
                    tool=tools[neighbor],
                    reason=f"{neighbor} requires {current_tool}",
                    relation="dependent",
                    weight=weight,
                )
            )
            seen.add(neighbor)

    # Priority 3: same-domain tools
    current_schema = tools[current_tool]
    if current_schema.domain:
        domain = current_schema.domain
        for name, t in tools.items():
            if name == current_tool or name in seen:
                continue
            if t.domain == domain:
                weight = 0.3 if name in used else 0.5
                suggestions.append(
                    NextToolSuggestion(
                        tool=t,
                        reason=f"same domain: {domain}",
                        relation="same_domain",
                        weight=weight,
                    )
                )
                seen.add(name)

    # Sort by weight (deprioritize used), then take top_k
    suggestions.sort(key=lambda s: s.weight, reverse=True)
    return suggestions[:top_k]
