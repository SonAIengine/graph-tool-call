"""Export ToolGraph to Neo4j Cypher CREATE statements."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph_tool_call.core.protocol import GraphEngine
    from graph_tool_call.core.tool import ToolSchema


def _escape(value: str) -> str:
    """Escape single quotes for Cypher string literals."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _sanitize_id(node_id: str) -> str:
    """Convert node ID to a valid Cypher variable name."""
    safe = node_id.replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_")
    # Prefix with 'n' if starts with digit
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe


def export_cypher(
    graph: GraphEngine,
    tools: dict[str, ToolSchema],
    path: str | Path,
) -> None:
    """Export the graph as Neo4j Cypher CREATE statements.

    The output file can be pasted into Neo4j Browser or run via ``cypher-shell``.
    """
    lines: list[str] = []

    # Nodes
    for node_id in graph.nodes():
        attrs = graph.get_node_attrs(node_id)
        raw_type = attrs.get("node_type", "Node")
        # Handle enum (e.g. NodeType.TOOL → "tool") or plain string
        type_val = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
        label = {"tool": "Tool", "category": "Category", "domain": "Domain"}.get(
            type_val.lower(), type_val.capitalize()
        )
        var = _sanitize_id(node_id)
        props: dict[str, str] = {"name": node_id}
        desc = attrs.get("description", "")
        if desc:
            props["description"] = str(desc)
        tags = attrs.get("tags")
        if tags:
            props["tags"] = ",".join(str(t) for t in tags)
        domain = attrs.get("domain")
        if domain:
            props["domain"] = str(domain)
        if node_id in tools:
            props["param_count"] = str(len(tools[node_id].parameters))

        prop_str = ", ".join(f"{k}: '{_escape(v)}'" for k, v in props.items())
        lines.append(f"CREATE ({var}:{label} {{{prop_str}}})")

    # Edges
    for src, tgt, attrs in graph.edges():
        raw_rel = attrs.get("relation", "RELATED_TO")
        rel_val = raw_rel.value if hasattr(raw_rel, "value") else str(raw_rel)
        relation = rel_val.upper().replace(" ", "_")
        src_var = _sanitize_id(src)
        tgt_var = _sanitize_id(tgt)
        edge_props: dict[str, str] = {}
        if "weight" in attrs:
            edge_props["weight"] = str(attrs["weight"])
        if "confidence" in attrs:
            edge_props["confidence"] = str(attrs["confidence"])
        if edge_props:
            prop_str = " {" + ", ".join(f"{k}: {v}" for k, v in edge_props.items()) + "}"
        else:
            prop_str = ""
        lines.append(f"CREATE ({src_var})-[:{relation}{prop_str}]->({tgt_var})")

    lines.append("")  # trailing newline
    Path(path).write_text(";\n".join(lines), encoding="utf-8")
