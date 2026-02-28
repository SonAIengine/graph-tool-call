"""Ontology schema: relation types, node types, and hierarchy definitions."""

from __future__ import annotations

from enum import Enum


class RelationType(str, Enum):
    """Edge relation types between tool nodes."""

    SIMILAR_TO = "similar_to"
    REQUIRES = "requires"
    COMPLEMENTARY = "complementary"
    CONFLICTS_WITH = "conflicts_with"
    BELONGS_TO = "belongs_to"


class NodeType(str, Enum):
    """Node types in the ontology graph."""

    TOOL = "tool"
    CATEGORY = "category"
    DOMAIN = "domain"


# Weights for relation types during retrieval scoring
DEFAULT_RELATION_WEIGHTS: dict[str, float] = {
    RelationType.SIMILAR_TO: 0.8,
    RelationType.REQUIRES: 1.0,
    RelationType.COMPLEMENTARY: 0.7,
    RelationType.CONFLICTS_WITH: 0.2,
    RelationType.BELONGS_TO: 0.5,
}
