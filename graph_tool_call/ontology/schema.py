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
    PRECEDES = "precedes"


class NodeType(str, Enum):
    """Node types in the ontology graph."""

    TOOL = "tool"
    CATEGORY = "category"
    DOMAIN = "domain"


class Confidence(str, Enum):
    """Edge confidence label, graphify-style.

    Every edge in a graphify-style ToolGraph carries one of three labels so
    downstream consumers (LLM agents, retrieval scoring, UI) can distinguish
    deterministic facts from heuristic guesses.

    EXTRACTED  — derived deterministically from the spec (path hierarchy,
                 shared $ref, CRUD pattern). conf_score >= 0.85 AND layer == 1.
    INFERRED   — heuristic match (name-based, RPC pattern, cross-resource).
                 conf_score >= 0.85 but not strictly structural.
    AMBIGUOUS  — low-confidence heuristic (0.70 <= conf_score < 0.85).
                 Surface in UI for review; retrieval applies a score penalty.
    """

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"


# Weights for relation types during retrieval scoring
DEFAULT_RELATION_WEIGHTS: dict[str, float] = {
    RelationType.SIMILAR_TO: 0.8,
    RelationType.REQUIRES: 1.0,
    RelationType.COMPLEMENTARY: 0.7,
    RelationType.CONFLICTS_WITH: 0.2,
    RelationType.BELONGS_TO: 0.5,
    RelationType.PRECEDES: 0.9,
}

# Intent-specific relation weights: boost relations that align with the query intent.
INTENT_RELATION_WEIGHTS: dict[str, dict[str, float]] = {
    "read": {
        RelationType.SIMILAR_TO: 1.0,  # same resource GET/LIST → very useful
        RelationType.REQUIRES: 0.8,
        RelationType.COMPLEMENTARY: 0.4,  # write ops less useful for read queries
        RelationType.CONFLICTS_WITH: 0.2,
        RelationType.BELONGS_TO: 0.6,
        RelationType.PRECEDES: 0.5,
    },
    "write": {
        RelationType.SIMILAR_TO: 0.5,  # GET less useful for write
        RelationType.REQUIRES: 1.0,  # preconditions matter
        RelationType.COMPLEMENTARY: 0.95,  # PATCH/PUT often together
        RelationType.CONFLICTS_WITH: 0.3,
        RelationType.BELONGS_TO: 0.5,
        RelationType.PRECEDES: 0.7,
    },
    "delete": {
        RelationType.SIMILAR_TO: 0.4,
        RelationType.REQUIRES: 0.9,  # need to know what to delete
        RelationType.COMPLEMENTARY: 0.3,
        RelationType.CONFLICTS_WITH: 0.5,  # conflicts more relevant for destructive ops
        RelationType.BELONGS_TO: 0.5,
        RelationType.PRECEDES: 0.8,
    },
}
