"""LLM-based automatic ontology construction (Phase 2 placeholder)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graph_tool_call.ontology.builder import OntologyBuilder


async def auto_organize(
    builder: OntologyBuilder,
    tools: list[Any],
    llm: Any = None,
) -> None:
    """Use an LLM to automatically organize tools into categories and relations.

    This is a Phase 2 feature. Currently raises NotImplementedError.
    """
    raise NotImplementedError(
        "auto_organize() will be available in Phase 2. "
        "Use OntologyBuilder.add_relation() and .assign_category() for manual setup."
    )
