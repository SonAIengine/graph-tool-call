"""LLM provider abstraction for ontology construction."""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.ontology.schema import RelationType


@dataclass
class ToolSummary:
    """Lightweight tool representation for LLM prompts.

    The optional fields (``method``, ``path``, ``response_fields``) extend the
    summary for semantic enrichment (``enrich_tool_semantics``). They are
    ignored by methods that don't need them, preserving backward compat.
    """

    name: str
    description: str
    parameters: list[str]  # just parameter names
    # Extended context for semantic enrichment (optional)
    method: str = ""
    path: str = ""
    response_fields: list[str] = field(default_factory=list)


@dataclass
class InferredRelation:
    """A relation inferred by an LLM."""

    source: str
    target: str
    relation_type: RelationType
    confidence: float
    reason: str


@dataclass
class FieldSemantic:
    """A field annotated with its semantic identifier.

    Used on both produces (what a tool outputs) and consumes (what it
    requires). ``json_path`` is set on produces; ``field`` is set on consumes.

    ``kind`` (consumes only) distinguishes two roles:
      - ``"data"``    — true data dependency (e.g. a business identifier
                        needed to address the operation). PathSynthesizer
                        will chain to a producer for this field.
      - ``"context"`` — ambient config (locale, site, pagination). Must be
                        supplied as an entity or collection default; the
                        synthesizer will NOT build a prerequisite chain
                        just to fetch it.

    The default ``"data"`` matches pre-kind behavior (safe for tools whose
    enrichment predates this schema change).
    """

    semantic: str
    json_path: str = ""
    field: str = ""
    kind: str = "data"


@dataclass
class PairHint:
    """A tool that pairs with the current tool in a workflow.

    ``source`` distinguishes ownership so re-running auto enrichment doesn't
    overwrite operator curation:
      - ``"auto"``   — produced by Pass 2a (per-tool batch) or Pass 2b
                       (cross-batch). Replaced on every Pass 2b re-run.
      - ``"manual"`` — added by an operator through the UI. Never overwritten
                       by automatic enrichment.

    Default ``"manual"`` is intentional: legacy data without a ``source``
    field gets the safer label, so a Pass 2b re-run does not silently delete
    pre-existing entries that may have been hand-curated.
    """

    tool: str
    reason: str = ""
    source: str = "manual"


@dataclass
class ToolEnrichment:
    """Per-tool semantic annotation produced by ``enrich_tool_semantics``.

    This is the Pass 2 output of the Plan-and-Execute L0 knowledge base.
    Used downstream by:
      - Stage 1 target selection (``when_to_use`` in catalog)
      - Stage 2 path synthesis (``produces_semantics`` / ``consumes_semantics``
        replace hardcoded synonym tables)
      - Graph edges (``pairs_well_with`` becomes semantic edges)
    """

    # canonical_action: search | read | create | update | delete | action
    canonical_action: str
    primary_resource: str  # e.g. "product"
    one_line_summary: str
    when_to_use: str
    when_not_to_use: str = ""
    produces_semantics: list[FieldSemantic] = field(default_factory=list)
    consumes_semantics: list[FieldSemantic] = field(default_factory=list)
    pairs_well_with: list[PairHint] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_RELATION_PROMPT = """\
Find relationships between these API tools.

Example:
Tools: createUser, getUserProfile, deleteUser
Answer: [
  {{"source": "getUserProfile", "target": "createUser",
    "relation": "REQUIRES", "confidence": 0.9, "reason": "need user to exist"}},
  {{"source": "createUser", "target": "deleteUser",
    "relation": "PRECEDES", "confidence": 0.8, "reason": "create before delete"}}
]

Relation types:
- REQUIRES: A needs B to run first (B provides data A needs)
- PRECEDES: A should run before B in a workflow

Tools:
{tools_list}

Output ONLY a JSON array. No explanation."""

_CATEGORY_PROMPT = """\
Group these API tools into logical categories. Each tool should belong to exactly one category.
{existing_categories}
Tools:
{tools_list}

Output a JSON object:
{{
  "categories": {{
    "category_name": ["tool1", "tool2"],
    ...
  }}
}}
Only output the JSON object, nothing else."""

_KEYWORD_ENRICHMENT_PROMPT = """\
Generate 3 search keywords for each tool. Use domain-specific synonyms a user would search for.
Do NOT use generic words (create, get, list, update, delete, user, data).

Example:
Tool: addToCart - Add a product to the shopping cart
Keywords: ["shopping basket", "reserve item", "cart insertion"]

Tools:
{tools_list}

Output ONLY a JSON object: {{"tool_name": ["keyword1", "keyword2", "keyword3"]}}"""

_EXAMPLE_QUERIES_PROMPT = """\
Write 2 natural language queries a user would type to find each tool.

Example:
Tool: requestRefund - Request a refund for an order
Queries: ["I want my money back", "process a return"]

Tools:
{tools_list}

Output ONLY a JSON object: {{"tool_name": ["query1", "query2"]}}"""

_VERIFY_RELATIONS_PROMPT = """\
Review these API relationships. Reply "keep" or "reject" for each.

Example:
- addToCart REQUIRES getProduct → keep (needs product ID)
- listUsers REQUIRES createUser → reject (listing works without creation)

Relations:
{relations_list}

Output ONLY JSON: [{{"source":"toolA","target":"toolB","verdict":"keep"}}]"""

_SUGGEST_MISSING_PROMPT = """\
Given these API tools and their existing relationships, suggest important \
MISSING relationships. Focus on workflow dependencies: which tool must \
run before which other tool?

Tools:
{tools_list}

Existing relationships:
{existing_relations}

Suggest 3-5 missing relationships that are clearly needed for common workflows.
Output ONLY a JSON array:
[{{"source":"toolA","target":"toolB","relation":"PRECEDES","confidence":0.9,"reason":"..."}}]"""


_ENRICH_SEMANTICS_PROMPT = """\
You are annotating API tools for a plan-and-execute planning system.
Produce structured metadata that downstream components use to (1) pick the
right tool for a user's goal, (2) synthesize execution plans, and (3) wire
one tool's output to another tool's input.
{reference_block}{vocab_block}
TOOLS TO ANNOTATE (this batch):
{batch_detailed}

For each tool in the batch, output a JSON object with these fields:
  - canonical_action: one of "search" | "read" | "create" | "update" | "delete" | "action"
  - primary_resource: one lowercase noun (e.g. "product", "order", "user", "shop", "category")
  - one_line_summary: short natural-language summary (<=60 chars)
  - when_to_use: 1-2 sentences describing the trigger condition
  - when_not_to_use: optional 1 sentence (can be empty) — alternative tool cases
  - produces_semantics: array of {{"semantic": "canonical_id", "json_path": "$.body..."}}
      * Include only MEANINGFUL fields (IDs, names, key metrics).
      * Skip pagination, headers, status codes.
      * Use CONSISTENT semantic ids across tools. If two tools both return a
        product identifier (one calls it "goodsNo", another "productId"),
        use the same semantic like "product_id".
  - consumes_semantics: array of {{"semantic": "canonical_id",
                                    "field": "paramName",
                                    "kind": "data" | "context"}}
      * REQUIRED inputs only. Skip optional filters, pagination.
      * Same semantic id conventions as produces.
      * kind="data" — business-data dependency: an identifier or value that
        addresses a specific record (e.g. product_id, order_id, user_id,
        search_keyword). A prior step in a plan normally produces it.
      * kind="context" — ambient/environmental config shared across the
        workflow (locale, site_no, tenant, pagination cursors, flag switches).
        The user or the caller supplies it as a default — it is NOT produced
        by a prior step. Use this for anything a plain UI user would set
        once per session, not per request.
  - pairs_well_with: array of {{"tool": "tool_name_from_available_list",
                                "reason": "brief reason"}}
      * 2-4 tools that typically precede or follow this tool.
      * Names MUST match the available list exactly. Do not invent.

OUTPUT FORMAT (strict):
{{
  "tool_name_1": {{...fields...}},
  "tool_name_2": {{...fields...}}
}}

STRICT RULES:
  - You MUST produce one entry for EVERY tool in the batch.
  - Do NOT skip tools with unclear descriptions — make your best guess.
  - Keep fields concise (short sentences) so all tools fit in the output.
  - Return JSON only. No markdown fences, no prose, no comments."""


# Pass 2b — cross-batch workflow pairing.
#
# Per-tool enrichment (Pass 2a) only sees one batch at a time, so it cannot
# spot pairs whose other half lives in a different batch. This prompt shows
# the entire collection's 1-line summaries so the LLM can suggest workflow
# successors that span resources.
#
# The output is batched (subset of tools per call) to stay within the
# response token budget — input stays full, output stays small.
_PAIRS_PROMPT = """\
You are reviewing an API tool collection to suggest workflow pairs.

For EACH tool in the OUTPUT BATCH, suggest 2-4 OTHER tools from the FULL
TOOL LIST that are commonly invoked just before or just after this tool in
a real-world workflow. Pairs SHOULD cross resource boundaries when there is
a natural business sequence (e.g. product detail → add to cart → checkout).

Pair quality matters more than quantity — only suggest tools you are
confident about. If a tool has no good pair candidates, return an empty
array for it.

FULL TOOL LIST (all available tools — pick pairs only from this list):
{full_list}

OUTPUT BATCH (suggest pairs ONLY for these tools):
{batch_list}

OUTPUT FORMAT (strict JSON):
{{
  "tool_name_1": [
    {{"tool": "other_tool_name", "reason": "short reason"}},
    ...
  ],
  "tool_name_2": [...],
  ...
}}

STRICT RULES:
  - You MUST include one entry for EVERY tool in the OUTPUT BATCH (use
    empty array if no good pairs).
  - Pair tool names MUST exactly match a name in the FULL TOOL LIST.
  - Do NOT pair a tool with itself.
  - Return JSON only. No markdown fences, no prose, no comments."""


def _format_tools_list(tools: list[ToolSummary]) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        params = ", ".join(t.parameters) if t.parameters else "none"
        lines.append(f"{i}. {t.name} - {t.description} (params: {params})")
    return "\n".join(lines)


def _format_tools_brief(tools: list[ToolSummary]) -> str:
    """Compact name list for the ``pairs_well_with`` reference.

    Name-only (no descriptions) to keep prompt small — descriptions would
    bloat the prompt by N× since every batch prompt contains this list.
    Tool names like ``seltSearchProduct`` already encode intent.
    """
    return "\n".join(f"- {t.name}" for t in tools)


def _format_tools_for_pairs(tools: list[ToolSummary]) -> str:
    """Compact ``name: 1-line summary`` block for Pass 2b prompts.

    Uses ``description`` (mapped from ai_metadata.one_line_summary by the
    caller for tools that have been Pass 2a annotated) so the LLM can pair
    based on workflow meaning, not just tool names.
    """
    lines = []
    for t in tools:
        summary = (t.description or "").strip().replace("\n", " ")
        if len(summary) > 100:
            summary = summary[:97] + "..."
        lines.append(f"- {t.name}: {summary}" if summary else f"- {t.name}")
    return "\n".join(lines)


def _format_tools_for_enrichment(tools: list[ToolSummary]) -> str:
    """Detailed per-tool block for enrichment prompt input."""
    blocks = []
    for t in tools:
        parts = [f"== {t.name} =="]
        if t.method and t.path:
            parts.append(f"HTTP: {t.method.upper()} {t.path}")
        if t.description:
            desc = t.description.strip()[:400]
            parts.append(f"Description: {desc}")
        if t.parameters:
            params = ", ".join(t.parameters[:25])
            parts.append(f"Request fields: {params}")
        if t.response_fields:
            resp = ", ".join(t.response_fields[:25])
            parts.append(f"Response fields: {resp}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def _parse_enrichment(data: Any) -> ToolEnrichment | None:
    """Build a ToolEnrichment from LLM JSON output. Tolerant of missing keys."""
    if not isinstance(data, dict):
        return None
    try:
        produces = [
            FieldSemantic(
                semantic=str(p.get("semantic", "")).strip(),
                json_path=str(p.get("json_path", "")).strip(),
            )
            for p in (data.get("produces_semantics") or [])
            if isinstance(p, dict) and str(p.get("semantic", "")).strip()
        ]
        consumes = []
        for c in data.get("consumes_semantics") or []:
            if not (isinstance(c, dict) and str(c.get("semantic", "")).strip()):
                continue
            raw_kind = str(c.get("kind", "data")).strip().lower()
            kind = raw_kind if raw_kind in ("data", "context") else "data"
            consumes.append(
                FieldSemantic(
                    semantic=str(c.get("semantic", "")).strip(),
                    field=str(c.get("field", "")).strip(),
                    kind=kind,
                )
            )
        # Pairs from per-tool enrichment are batch-scoped (LLM only sees the
        # current batch), so quality is lower than cross-batch Pass 2b.
        # Marked source="auto" so a Pass 2b run can replace them while
        # preserving operator-curated source="manual" entries.
        pairs = [
            PairHint(
                tool=str(p.get("tool", "")).strip(),
                reason=str(p.get("reason", "")).strip(),
                source="auto",
            )
            for p in (data.get("pairs_well_with") or [])
            if isinstance(p, dict) and str(p.get("tool", "")).strip()
        ]
        action = str(data.get("canonical_action", "")).strip().lower()
        resource = str(data.get("primary_resource", "")).strip().lower()
        return ToolEnrichment(
            canonical_action=action,
            primary_resource=resource,
            one_line_summary=str(data.get("one_line_summary", "")).strip(),
            when_to_use=str(data.get("when_to_use", "")).strip(),
            when_not_to_use=str(data.get("when_not_to_use", "")).strip(),
            produces_semantics=produces,
            consumes_semantics=consumes,
            pairs_well_with=pairs,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _parse_relation_type(s: str) -> RelationType | None:
    mapping = {
        "REQUIRES": RelationType.REQUIRES,
        "PRECEDES": RelationType.PRECEDES,
        "COMPLEMENTARY": RelationType.COMPLEMENTARY,
        "SIMILAR_TO": RelationType.SIMILAR_TO,
        "CONFLICTS_WITH": RelationType.CONFLICTS_WITH,
    }
    return mapping.get(s.upper())


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response, with aggressive recovery for small models.

    Handles:
    - Markdown code blocks (```json ... ```)
    - Thinking tags (<think>...</think>)
    - Trailing text after JSON
    - Truncated JSON (attempts to close brackets)
    """
    text = text.strip()

    # Remove <think>...</think> blocks (qwen3 thinking mode)
    import re as _re

    text = _re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Remove markdown code blocks
    if "```" in text:
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON array or object in the text
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching end bracket
        end = text.rfind(end_char)
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Try to fix truncated JSON by closing brackets
        fragment = text[start:]
        open_brackets = fragment.count(start_char) - fragment.count(end_char)
        if open_brackets > 0:
            fragment += end_char * open_brackets
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                pass

    # Last resort: try to find any valid JSON substring
    raise json.JSONDecodeError("No valid JSON found", text, 0)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class OntologyLLM(ABC):
    """Abstract base class for LLM providers used in ontology construction."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a response from the LLM."""

    def infer_relations(
        self,
        tools: list[ToolSummary],
        batch_size: int = 15,
    ) -> list[InferredRelation]:
        """Infer relations between tools using the LLM."""
        all_relations: list[InferredRelation] = []

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            prompt = _RELATION_PROMPT.format(tools_list=_format_tools_list(batch))
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if not isinstance(parsed, list):
                    continue
                for item in parsed:
                    rel_type = _parse_relation_type(item.get("relation", ""))
                    if rel_type is None:
                        continue
                    all_relations.append(
                        InferredRelation(
                            source=item["source"],
                            target=item["target"],
                            relation_type=rel_type,
                            confidence=float(item.get("confidence", 0.8)),
                            reason=item.get("reason", ""),
                        )
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return all_relations

    def suggest_categories(
        self,
        tools: list[ToolSummary],
        existing_categories: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Suggest category groupings for tools."""
        existing_str = ""
        if existing_categories:
            existing_str = (
                "\nExisting categories (reuse these instead of creating duplicates): "
                + ", ".join(existing_categories)
                + "\n"
            )
        prompt = _CATEGORY_PROMPT.format(
            tools_list=_format_tools_list(tools),
            existing_categories=existing_str,
        )
        response = self.generate(prompt)

        try:
            parsed = _extract_json(response)
            categories = parsed.get("categories", {})
            if isinstance(categories, dict):
                return {k: v for k, v in categories.items() if isinstance(v, list)}
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass

        return {}

    def verify_relations(
        self,
        relations: list[InferredRelation],
        tools: list[ToolSummary],
        batch_size: int = 10,
    ) -> tuple[list[InferredRelation], list[InferredRelation]]:
        """Verify auto-detected relations using the LLM.

        Returns (kept, rejected) — two lists of relations.
        The LLM reviews each relation and decides keep/reject/fix.
        """
        kept: list[InferredRelation] = []
        rejected: list[InferredRelation] = []

        for i in range(0, len(relations), batch_size):
            batch = relations[i : i + batch_size]
            rels_text = "\n".join(
                f"- {r.source} {r.relation_type.name} {r.target} ({r.reason[:60]})" for r in batch
            )
            prompt = _VERIFY_RELATIONS_PROMPT.format(
                relations_list=rels_text,
            )
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if not isinstance(parsed, list):
                    # If parsing fails, keep all (conservative)
                    kept.extend(batch)
                    continue

                verdict_map = {
                    (item.get("source", ""), item.get("target", "")): item.get("verdict", "keep")
                    for item in parsed
                    if isinstance(item, dict)
                }

                for rel in batch:
                    verdict = verdict_map.get((rel.source, rel.target), "keep")
                    if verdict == "reject":
                        rejected.append(rel)
                    else:
                        kept.append(rel)

            except (json.JSONDecodeError, KeyError, TypeError):
                # On parse failure, keep all (conservative)
                kept.extend(batch)

        return kept, rejected

    def suggest_missing(
        self,
        tools: list[ToolSummary],
        existing_relations: list[InferredRelation],
    ) -> list[InferredRelation]:
        """Suggest missing relations that the heuristic missed.

        The LLM sees the current tools and relations, then suggests
        important workflow dependencies that are absent.
        """
        tools_text = _format_tools_list(tools[:30])
        existing_text = "\n".join(
            f"- {r.source} {r.relation_type.name} {r.target}" for r in existing_relations[:30]
        )
        prompt = _SUGGEST_MISSING_PROMPT.format(
            tools_list=tools_text,
            existing_relations=existing_text or "(none)",
        )
        response = self.generate(prompt)

        suggestions: list[InferredRelation] = []
        try:
            parsed = _extract_json(response)
            if not isinstance(parsed, list):
                return suggestions
            for item in parsed:
                rel_type = _parse_relation_type(item.get("relation", ""))
                if rel_type is None:
                    continue
                suggestions.append(
                    InferredRelation(
                        source=item["source"],
                        target=item["target"],
                        relation_type=rel_type,
                        confidence=float(item.get("confidence", 0.8)),
                        reason=item.get("reason", "LLM suggested"),
                    )
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return suggestions

    def enrich_keywords(
        self,
        tools: list[ToolSummary],
        batch_size: int = 15,
    ) -> dict[str, list[str]]:
        """Generate English search keywords for tools to improve BM25 retrieval.

        Returns a dict of tool_name -> list of keywords.
        """
        all_keywords: dict[str, list[str]] = {}

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            prompt = _KEYWORD_ENRICHMENT_PROMPT.format(tools_list=_format_tools_list(batch))
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if isinstance(parsed, dict):
                    for name, keywords in parsed.items():
                        if isinstance(keywords, list):
                            all_keywords[name] = [str(k) for k in keywords]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return all_keywords

    def generate_example_queries(
        self,
        tools: list[ToolSummary],
        batch_size: int = 15,
    ) -> dict[str, list[str]]:
        """Generate natural language example queries for each tool.

        These are used to enrich embedding text so that user queries
        match tool embeddings more closely.

        Returns a dict of tool_name -> list of example queries.
        """
        all_queries: dict[str, list[str]] = {}

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            prompt = _EXAMPLE_QUERIES_PROMPT.format(tools_list=_format_tools_list(batch))
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if isinstance(parsed, dict):
                    for name, queries in parsed.items():
                        if isinstance(queries, list):
                            all_queries[name] = [str(q) for q in queries]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return all_queries

    def enrich_pairs(
        self,
        tools: list[ToolSummary],
        batch_size: int = 30,
    ) -> dict[str, list[PairHint]]:
        """Pass 2b — cross-batch workflow pair suggestion.

        Unlike Pass 2a (``enrich_tool_semantics``) which sees only the
        current batch, this pass shows the LLM the full collection's 1-line
        summaries so it can suggest pairs that cross resource boundaries
        (e.g. ``getProductDetail → addToCart`` even when the two tools live
        in different swagger sources).

        Output is batched only on the OUTPUT axis: input list stays full
        for every call, output covers ``batch_size`` tools per call. This
        keeps the prompt short and avoids the 8k-token output limit
        truncating long pair lists.

        Tools should arrive with ``description`` set to ai_metadata
        ``one_line_summary`` when available (Pass 2a output) so pairing can
        rely on workflow meaning, not just tool names.

        Returns: {tool_name: [PairHint(source="auto"), ...]}
        """
        results: dict[str, list[PairHint]] = {}
        if not tools:
            return results

        full_list = _format_tools_for_pairs(tools)

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            batch_list = _format_tools_for_pairs(batch)
            prompt = _PAIRS_PROMPT.format(full_list=full_list, batch_list=batch_list)
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if not isinstance(parsed, dict):
                    continue
                for name, raw_pairs in parsed.items():
                    if not isinstance(raw_pairs, list):
                        continue
                    pair_list: list[PairHint] = []
                    for p in raw_pairs:
                        if not isinstance(p, dict):
                            continue
                        target = str(p.get("tool", "")).strip()
                        if not target or target == name:
                            continue
                        pair_list.append(
                            PairHint(
                                tool=target,
                                reason=str(p.get("reason", "")).strip(),
                                source="auto",
                            )
                        )
                    results[str(name)] = pair_list
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return results

    def enrich_tool_semantics(
        self,
        tools: list[ToolSummary],
        batch_size: int = 10,
        *,
        reference_tools: list[ToolSummary] | None = None,
        existing_vocab: list[str] | None = None,
        valid_tool_names: set[str] | None = None,
    ) -> dict[str, ToolEnrichment]:
        """Per-tool semantic annotation for Plan-and-Execute architecture.

        ``tools`` = the batch(es) to produce detailed enrichment for.

        ``reference_tools`` (optional, default ``None``) — when supplied,
        rendered as a brief tool list in the prompt so the LLM can pick
        ``pairs_well_with`` from valid names. **Streaming callers should
        usually pass ``None``** — Pass 2b handles pairs in a separate
        cross-batch call, and skipping the reference block saves ~50%
        prompt tokens. The pair list emitted in this pass is post-validated
        against ``valid_tool_names`` instead.

        ``existing_vocab`` (optional) — accumulated semantic ids decided in
        previous batches of the same enrichment run. The LLM is asked to
        reuse these labels when applicable, which keeps cross-batch vocab
        consistent (avoids ``product_id`` vs ``productId`` divergence).
        Streaming callers should pass the unique semantics seen so far.

        ``valid_tool_names`` (optional) — full set of tool names in the
        collection. When supplied, ``pairs_well_with`` entries pointing to
        tools outside this set are dropped silently (LLM hallucination
        guard). When ``reference_tools`` is None the LLM only knows the
        names in the current batch; without this guard it would invent
        names for cross-batch pairs.
        """
        results: dict[str, ToolEnrichment] = {}
        if not tools:
            return results

        ref_block = ""
        if reference_tools:
            ref_block = (
                "\nAVAILABLE TOOLS IN THE COLLECTION (names + 1-line "
                "descriptions, for pairs_well_with reference):\n"
                + _format_tools_brief(reference_tools)
                + "\n"
            )

        vocab_block = ""
        if existing_vocab:
            vocab_block = (
                "\nEXISTING SEMANTIC VOCABULARY (reuse these canonical ids "
                "when the field has the same meaning — keeps cross-batch "
                "labels consistent):\n"
                + "\n".join(f"- {s}" for s in sorted(set(existing_vocab)))
                + "\n"
            )

        for i in range(0, len(tools), batch_size):
            batch = tools[i : i + batch_size]
            prompt = _ENRICH_SEMANTICS_PROMPT.format(
                reference_block=ref_block,
                vocab_block=vocab_block,
                batch_detailed=_format_tools_for_enrichment(batch),
            )
            response = self.generate(prompt)

            try:
                parsed = _extract_json(response)
                if not isinstance(parsed, dict):
                    continue
                for name, data in parsed.items():
                    enrichment = _parse_enrichment(data)
                    if enrichment is None or not enrichment.canonical_action:
                        continue
                    # Hallucination guard for pairs_well_with — drop entries
                    # whose target name is not in the catalog.
                    if valid_tool_names is not None:
                        enrichment.pairs_well_with = [
                            p
                            for p in enrichment.pairs_well_with
                            if p.tool in valid_tool_names and p.tool != str(name)
                        ]
                    results[str(name)] = enrichment
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return results


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------


class OllamaOntologyLLM(OntologyLLM):
    """Ollama local model provider."""

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            }
        ).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
            return result.get("response", "")


# ---------------------------------------------------------------------------
# OpenAI-Compatible Provider
# ---------------------------------------------------------------------------


class OpenAICompatibleOntologyLLM(OntologyLLM):
    """OpenAI-compatible API provider (works with OpenAI, vLLM, llama-server, etc.)."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        max_tokens: int = 8192,
        timeout: int = 300,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        # max_tokens 를 명시 지정하지 않으면 provider 기본값 (일부 모델은 4096)
        # 으로 잘려서 batch enrichment JSON 이 중간에 truncate → 일부 tool 누락.
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": self.max_tokens,
            }
        ).encode()

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""


# ---------------------------------------------------------------------------
# Callable Adapter
# ---------------------------------------------------------------------------


class CallableOntologyLLM(OntologyLLM):
    """Wraps any callable ``(str) -> str`` as an OntologyLLM."""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def generate(self, prompt: str) -> str:
        result = self._fn(prompt)
        if isinstance(result, str):
            return result
        return str(result)


# ---------------------------------------------------------------------------
# OpenAI Client Adapter
# ---------------------------------------------------------------------------


class OpenAIClientOntologyLLM(OntologyLLM):
    """Wraps an OpenAI client instance (openai.OpenAI or similar)."""

    def __init__(self, client: Any, model: str = "gpt-4o-mini") -> None:
        self._client = client
        self._model = model

    def generate(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Auto-wrap any LLM input
# ---------------------------------------------------------------------------


def wrap_llm(llm: Any) -> OntologyLLM:
    """Auto-detect LLM type and wrap as OntologyLLM.

    Supported inputs:

    - ``OntologyLLM`` instance — returned as-is
    - ``callable(str) -> str`` — wrapped with CallableOntologyLLM
    - OpenAI client (has ``chat.completions``) — wrapped with OpenAIClientOntologyLLM
    - ``str`` shorthand — parsed as provider/model:
        - ``"ollama/qwen2.5:7b"`` → OllamaOntologyLLM
        - ``"openai/gpt-4o-mini"`` → OpenAICompatibleOntologyLLM
        - ``"litellm/..."`` → uses litellm.completion via CallableOntologyLLM

    Examples::

        wrap_llm(OllamaOntologyLLM())           # pass-through
        wrap_llm(lambda p: my_llm(p))            # callable
        wrap_llm(openai.OpenAI())                # OpenAI client
        wrap_llm("ollama/qwen2.5:7b")            # string shorthand
    """
    if isinstance(llm, OntologyLLM):
        return llm

    # String shorthand: "provider/model"
    if isinstance(llm, str):
        return _wrap_string(llm)

    # OpenAI-like client: has chat.completions.create
    if hasattr(llm, "chat") and hasattr(llm.chat, "completions"):
        return OpenAIClientOntologyLLM(llm)

    # Callable: (str) -> str
    if callable(llm):
        return CallableOntologyLLM(llm)

    msg = (
        f"Cannot auto-wrap {type(llm).__name__} as OntologyLLM. "
        "Pass an OntologyLLM instance, a callable(str)->str, "
        "an OpenAI client, or a string like 'ollama/qwen2.5:7b'."
    )
    raise TypeError(msg)


def _wrap_string(spec: str) -> OntologyLLM:
    """Parse a 'provider/model' string into an OntologyLLM."""
    if "/" not in spec:
        msg = f"LLM string must be 'provider/model', got: {spec!r}"
        raise ValueError(msg)

    provider, model = spec.split("/", 1)
    provider = provider.lower()

    if provider == "ollama":
        return OllamaOntologyLLM(model=model)

    if provider == "openai":
        import os

        return OpenAICompatibleOntologyLLM(
            model=model,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )

    if provider == "litellm":

        def _litellm_fn(prompt: str) -> str:
            try:
                import litellm
            except ImportError:
                raise ImportError(
                    "litellm is required for 'litellm/...' shorthand. "
                    "Install with: pip install litellm"
                )
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content or ""

        return CallableOntologyLLM(_litellm_fn)

    # Generic OpenAI-compatible with provider as base_url hint
    return OpenAICompatibleOntologyLLM(model=model)
