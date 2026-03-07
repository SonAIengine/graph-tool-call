"""Commerce domain preset — order/payment/shipping workflow patterns.

Automatically detects commerce API patterns and applies domain-specific
PRECEDES relations with boosted confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import RelationType

# Commerce workflow stages (ordered)
_COMMERCE_STAGES = [
    "cart",
    "checkout",
    "order",
    "payment",
    "fulfillment",
    "shipping",
    "delivery",
    "return",
    "refund",
]

# Keywords that indicate each stage
_STAGE_KEYWORDS: dict[str, list[str]] = {
    "cart": ["cart", "basket", "bag"],
    "checkout": ["checkout", "check_out"],
    "order": ["order", "purchase"],
    "payment": ["payment", "pay", "charge", "transaction", "invoice", "billing"],
    "fulfillment": ["fulfill", "fulfilment", "fulfillment", "pack", "warehouse"],
    "shipping": ["ship", "shipping", "shipment", "dispatch", "courier", "tracking"],
    "delivery": ["deliver", "delivery"],
    "return": ["return", "rma", "exchange"],
    "refund": ["refund", "credit", "chargeback"],
}

# Order lifecycle sub-patterns
_ORDER_LIFECYCLE = ["create", "confirm", "process", "complete", "cancel"]


@dataclass
class CommerceRelation:
    """A commerce-domain specific relation."""

    source: str
    target: str
    relation_type: RelationType
    confidence: float
    stage_source: str
    stage_target: str


def detect_commerce_patterns(tools: list[ToolSchema]) -> list[CommerceRelation]:
    """Detect commerce API workflow patterns among tools.

    Returns PRECEDES relations based on commerce domain knowledge.
    """
    # Classify tools by commerce stage
    tool_stages: dict[str, list[str]] = {}  # tool_name -> list of stages
    for tool in tools:
        stages = _classify_stage(tool)
        if stages:
            tool_stages[tool.name] = stages

    if len(tool_stages) < 2:
        return []

    relations: list[CommerceRelation] = []

    # Cross-stage PRECEDES: cart → order → payment → shipping → delivery
    for tool_a in tools:
        stages_a = tool_stages.get(tool_a.name, [])
        for tool_b in tools:
            if tool_a.name == tool_b.name:
                continue
            stages_b = tool_stages.get(tool_b.name, [])
            for sa in stages_a:
                for sb in stages_b:
                    idx_a = _COMMERCE_STAGES.index(sa) if sa in _COMMERCE_STAGES else -1
                    idx_b = _COMMERCE_STAGES.index(sb) if sb in _COMMERCE_STAGES else -1
                    if idx_a >= 0 and idx_b >= 0 and idx_a < idx_b:
                        # Only add if stages are adjacent or close
                        if idx_b - idx_a <= 2:
                            relations.append(
                                CommerceRelation(
                                    source=tool_a.name,
                                    target=tool_b.name,
                                    relation_type=RelationType.PRECEDES,
                                    confidence=0.9 if idx_b - idx_a == 1 else 0.75,
                                    stage_source=sa,
                                    stage_target=sb,
                                )
                            )

    # Deduplicate: keep highest confidence per pair
    best: dict[tuple[str, str], CommerceRelation] = {}
    for r in relations:
        key = (r.source, r.target)
        if key not in best or r.confidence > best[key].confidence:
            best[key] = r

    return sorted(best.values(), key=lambda r: r.confidence, reverse=True)


def is_commerce_api(tools: list[ToolSchema]) -> bool:
    """Check if the tool set appears to be a commerce API.

    Returns True if at least 3 different commerce stages are detected.
    """
    stages_found: set[str] = set()
    for tool in tools:
        stages = _classify_stage(tool)
        stages_found.update(stages)
    return len(stages_found) >= 3


def apply_commerce_preset(tg: Any, *, min_confidence: float = 0.7) -> int:
    """Detect and apply commerce workflow relations to a ToolGraph.

    Returns the number of relations added.
    """
    tools_list = list(tg.tools.values())
    relations = detect_commerce_patterns(tools_list)
    added = 0
    for r in relations:
        if r.confidence < min_confidence:
            continue
        if not tg.graph.has_edge(r.source, r.target):
            tg.add_relation(r.source, r.target, r.relation_type)
            added += 1
    return added


def _classify_stage(tool: ToolSchema) -> list[str]:
    """Classify a tool into commerce stages based on name, description, tags, and path."""
    text_parts = [tool.name, tool.description]
    text_parts.extend(tool.tags)
    path = tool.metadata.get("path", "")
    if path:
        text_parts.append(path)
    text = " ".join(text_parts).lower()
    # Normalize separators
    text = re.sub(r"[_\-/.]", " ", text)

    stages: list[str] = []
    for stage, keywords in _STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                stages.append(stage)
                break

    return stages
