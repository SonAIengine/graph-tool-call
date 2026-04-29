"""PathSynthesizer — Stage 2 of Plan-and-Execute.

Given a target tool and user-provided entities, walk the ToolGraph's
produces/consumes metadata backwards to construct a Plan (ordered steps +
bindings) that, when executed by PlanRunner, satisfies the target.

This module is transport-agnostic. It consumes a plain ``graph`` dict (the
shape persisted as ``api_tool_collections.graph.graph``) — no DB, no HTTP.

v1 scope (per design §16.6):
  - Linear chain only — no fan-out, no parallel, no branching.
  - Max recursion depth = 5 (guard against cyclic or pathological graphs).

Matching order for each required consume field:
  1. User ``entities`` (Stage 1 output) — preferred, no extra step.
  2. Another tool's ``produces`` with the same ``semantic_tag``
     (Pass 2 LLM enrichment quality).
  3. Another tool's ``produces`` with the same ``field_name``
     (Pass 1 deterministic extraction, fallback).

Producer selection is ranked by Pass 2 metadata signals — no hardcoded
domain or field rules:
  - Entity affinity: producer consumes an entity the user supplied,
    so chaining through it actually uses that entity.
  - Pair hint: target's ``pairs_well_with`` includes this producer.
  - Action preference: ``canonical_action`` = search/read fits a
    prerequisite role better than create/update/delete.

``consumes[].kind`` ("data" | "context", set by Pass 2):
  - "data" — chain to a producer if entity doesn't match.
  - "context" — ambient config (locale, site, tenant). Never chained;
    must come from entity or skipped (runtime uses API default).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graph_tool_call.plan.schema import Plan, PlanStep


class PlanSynthesisError(Exception):
    """Base class for synthesis failures."""


class UnsatisfiableFieldError(PlanSynthesisError):
    """A required field cannot be supplied by entities or any producer."""


class CyclicDependencyError(PlanSynthesisError):
    """The synthesis trace revisits a tool already in progress."""


class MaxDepthExceededError(PlanSynthesisError):
    """Recursion depth exceeded — likely a misshapen graph."""


class DynamicOptionRequired(UnsatisfiableFieldError):
    """A required data field has a single-hop producer that can be called
    immediately with the user's entities + context_defaults. Surface this
    so the caller can fetch the option list (instead of weaving a chain)
    and ask the user to pick — the popup-driven UX for fields like
    ``itmNo`` (single-품목 option) where the choices are dynamic per
    request.

    The exception carries enough metadata for the caller to:
      * know which producer to call (``producer_name``)
      * find the option array in the producer's response (``options_path``)
      * pick a sensible label field next to each code (``label_field_hints``)
    """

    def __init__(
        self,
        message: str,
        *,
        field_name: str,
        semantic_tag: str,
        producer_name: str,
        options_path: str,
        label_field_hints: list[str],
    ) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.semantic_tag = semantic_tag
        self.producer_name = producer_name
        self.options_path = options_path
        self.label_field_hints = list(label_field_hints)


def _normalize_field_name(name: str) -> str:
    """Lowercase + strip separators for loose field-name matching.

    Conservative on purpose:
      ``ordNo`` → ``ordno``
      ``ord_no`` → ``ordno``
      ``ORD-NO`` → ``ordno``
    BUT keeps token roots distinct:
      ``ordNo`` ≠ ``orderNo`` (``ordno`` ≠ ``orderno``)
    Token-level synonym mapping (``ord`` ↔ ``order``) is domain-specific
    and not done here — the graph-edge fallback handles those cases.
    """
    if not name:
        return ""
    out: list[str] = []
    for ch in name:
        if ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def _normalize_field_name(name: str) -> str:
    """Lowercase + strip non-alphanumerics for loose field-name matching.

    Conservative on purpose:
      ``ordNo`` → ``ordno``    ``ord_no`` → ``ordno``    ``ORD-NO`` → ``ordno``

    Token roots stay distinct:
      ``ordNo`` ≠ ``orderNo``  (``ordno`` ≠ ``orderno``)

    Token-level synonym mapping (``ord`` ↔ ``order``) is domain-specific
    and intentionally NOT done here — that's the job of the graph-edge
    fallback in ``_find_producer``, which uses path/$ref/CRUD signals
    instead of name guessing.
    """
    if not name:
        return ""
    return "".join(ch.lower() for ch in name if ch.isalnum())


@dataclass
class _PartialStep:
    """In-progress step being built during bottom-up synthesis."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    step_id: str = ""                          # assigned at topological sort


class PathSynthesizer:
    """Deterministic plan builder driven by graph ``produces``/``consumes``.

    Usage::

        syn = PathSynthesizer(graph_dict)
        plan = syn.synthesize(
            target="seltProductDetailInfo",
            entities={"search_keyword": "quarzen 티셔츠"},
        )
    """

    def __init__(
        self,
        graph: dict[str, Any],
        *,
        max_depth: int = 5,
        context_defaults: dict[str, Any] | None = None,
        enum_field_names: set[str] | None = None,
    ) -> None:
        self._tools: dict[str, dict[str, Any]] = dict(graph.get("tools") or {})
        self._max_depth = max_depth
        # Collection-level ambient values (locale, tenant id, site id, ...) the
        # operator registers once per collection. Filled into ``kind=context``
        # consume fields when the user's entities don't supply them — avoids
        # repeating env-style args in every requirement and avoids leaking
        # backend-specific defaults into library code. Lookup precedence:
        # entities > context_defaults > skip.
        self._context_defaults: dict[str, Any] = dict(context_defaults or {})
        # Field names the operator registered an enum mapping for. When a
        # required-data field of this kind can't be filled by an entity,
        # the synthesizer raises UnsatisfiableFieldError instead of
        # producer-chaining — the caller (service layer) is expected to
        # surface a popup to the user rather than weaving an awkward
        # producer chain that pulls in unrelated tools just to source a
        # code value. User intent (popup choice) wins over chain depth.
        self._enum_field_names: set[str] = set(enum_field_names or ())
        # semantic_tag -> [tool_name], insertion order preserved
        self._producers_by_semantic: dict[str, list[str]] = {}
        self._producers_by_field: dict[str, list[str]] = {}
        # Loose-field index: normalised field name → [tool_name].
        # Lets ``ordNo`` match producers of ``ordno`` / ``ord_no`` / ``ORDNO``.
        # Conservative — only normalises case + separators, never strips
        # tokens (so ``ordNo`` ≠ ``orderNo`` — those need the graph fallback).
        self._producers_by_loose_field: dict[str, list[str]] = {}
        # graphify-mode adjacency: ``tool_name -> [edge_dict]`` for outgoing
        # workflow edges (REQUIRES / PRECEDES / COMPLEMENTARY). Used as a
        # fallback in ``_find_producer`` when neither semantic_tag nor
        # field_name match — we walk the graph the user/extractor built
        # rather than failing on field-name divergence.
        self._workflow_edges_out: dict[str, list[dict[str, Any]]] = {}
        self._index_workflow_edges(graph)
        self._build_producer_indexes()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        *,
        target: str,
        entities: dict[str, Any] | None = None,
        goal: str = "",
    ) -> Plan:
        """Build a Plan whose final step is ``target`` with required args
        filled by entities + prerequisite steps.

        Raises ``UnsatisfiableFieldError`` if a required field has no
        producer or entity mapping.
        """
        if target not in self._tools:
            raise PlanSynthesisError(f"target tool not in graph: {target!r}")

        entities = entities or {}
        steps_by_tool: dict[str, _PartialStep] = {}
        visiting: set[str] = set()

        # Resolve recursively; populates steps_by_tool with target at the end
        self._resolve(
            tool_name=target,
            entities=entities,
            steps_by_tool=steps_by_tool,
            visiting=visiting,
            depth=0,
        )

        # Assign topological ids s1..sN by insertion order
        ordered_tools = list(steps_by_tool.keys())
        for idx, tool_name in enumerate(ordered_tools, start=1):
            steps_by_tool[tool_name].step_id = f"s{idx}"

        # Replace tool-name bindings with step-id bindings
        final_steps: list[PlanStep] = []
        for tool_name in ordered_tools:
            partial = steps_by_tool[tool_name]
            args = {
                k: self._rewrite_tool_refs(v, steps_by_tool)
                for k, v in partial.args.items()
            }
            final_steps.append(PlanStep(
                id=partial.step_id,
                tool=partial.tool,
                args=args,
                rationale=partial.rationale,
                response_root_keys=self._response_root_keys(tool_name),
            ))

        target_step_id = steps_by_tool[target].step_id

        # Collect user_input slots so the runner can prompt the caller in
        # advance and the UI can render a single popup with all missing
        # fields, instead of one popup per step. Each entry: which step
        # needs which field, and (when known) the original semantic_tag
        # so frontend can show the same enum/popup the operator
        # registered for that field.
        user_input_slots: list[dict[str, Any]] = []
        for step in final_steps:
            for arg_name, arg_val in (step.args or {}).items():
                if isinstance(arg_val, str) and arg_val.startswith("${user_input."):
                    user_input_slots.append({
                        "step_id": step.id,
                        "tool": step.tool,
                        "field_name": arg_name,
                    })

        return Plan(
            id=str(uuid.uuid4()),
            goal=goal or f"Execute {target}",
            steps=final_steps,
            # PlanRunner adapter 는 step ctx 에 응답 body 를 root 로 노출 →
            # ``${sN}`` 만으로 전체 응답 dict 가 잡힌다 (과거 ``${sN.body}`` 는
            # adapter 가 ``{status, body}`` 을 그대로 흘릴 때의 흔적).
            output_binding=f"${{{target_step_id}}}",
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "target": target,
                "entities": dict(entities),
                "synthesized_by": "PathSynthesizer/v1",
                "user_input_slots": user_input_slots,
            },
        )

    # ------------------------------------------------------------------
    # core recursion
    # ------------------------------------------------------------------

    def _resolve(
        self,
        *,
        tool_name: str,
        entities: dict[str, Any],
        steps_by_tool: dict[str, _PartialStep],
        visiting: set[str],
        depth: int,
    ) -> str:
        """Ensure ``tool_name`` has a PartialStep with resolved args.

        Returns the tool name itself (used as a placeholder in args until
        step_ids are assigned by the caller).
        """
        if depth > self._max_depth:
            raise MaxDepthExceededError(
                f"synthesis exceeded max_depth={self._max_depth} at {tool_name!r}"
            )
        if tool_name in steps_by_tool:
            return tool_name
        if tool_name in visiting:
            raise CyclicDependencyError(
                f"cycle detected at {tool_name!r} (chain: {sorted(visiting)!r})"
            )
        visiting.add(tool_name)

        tool = self._tools.get(tool_name) or {}
        metadata = tool.get("metadata") or {}
        consumes = metadata.get("consumes") or []

        args: dict[str, Any] = {}
        rationales: list[str] = []

        for consume in consumes:
            field_name = consume.get("field_name") or ""
            semantic = consume.get("semantic_tag") or ""
            kind = str(consume.get("kind") or "data").strip().lower()
            is_required = bool(consume.get("required"))

            # 1. Entity match (user-supplied) — applies to both data and
            #    context, both required and optional. The user's input
            #    always wins.
            entity_val = self._match_entity(entities, semantic, field_name)
            if entity_val is not None:
                args[field_name] = entity_val
                continue

            # 2. Context-kind: try collection-level defaults regardless of
            #    required flag. Context is never chained — ambient config
            #    must come from entity or operator-registered default
            #    (chaining through e.g. getSiteInfo would inflate the plan
            #    with steps that don't produce business value).
            if kind == "context":
                default = self._lookup_context_default(semantic, field_name)
                if default is not None:
                    args[field_name] = default
                continue

            # 3. Optional data field: leave out. The caller's backend will
            #    apply its own defaults — synthesizer has no business
            #    inventing values for optional business inputs.
            if not is_required:
                continue

            # 4. Enum-field popup priority. If the operator registered an
            #    enum mapping for this field, it's the kind of value the
            #    user should pick from a popup — NOT something to chain
            #    through a producer (which often drags in semantically
            #    unrelated tools just because their response happens to
            #    contain a code by the same name). Surface
            #    UnsatisfiableFieldError so the caller can yield a
            #    question.required event instead.
            if field_name in self._enum_field_names:
                raise UnsatisfiableFieldError(
                    f"tool {tool_name!r} requires {field_name!r} "
                    f"(semantic={semantic!r}) — enum field, expects user "
                    f"selection (no producer chain attempted)"
                )

            # 5. Required data field → rank candidate producers and pick the best.
            #    Pass ``visiting`` as ``excluded`` so cycle-prone candidates are
            #    skipped here (Cycle policy A). The chain reroutes around the
            #    cycle when an alternative producer exists; only when none
            #    remains does the caller fall through to user-input slot (F2).
            producer = self._find_producer(
                semantic=semantic, field_name=field_name,
                target_tool=tool_name, entities=entities,
                excluded=visiting,
            )
            if producer is None:
                # F2 + Cycle policy B: gracefully surface the field as a
                # ``${user_input.<field>}`` placeholder rather than aborting
                # the entire plan. The runner detects the placeholder at
                # step-start and asks the user (or its surrounding agent)
                # to supply the value. The plan's metadata records every
                # such slot so the caller can pre-collect inputs.
                placeholder = f"${{user_input.{field_name}}}"
                args[field_name] = placeholder
                rationales.append(f"{field_name} ← user_input")
                continue

            # 5a. Dynamic-option popup priority. Detect "read-detail then
            #     pick one" patterns where the producer is a single-hop
            #     read of a product/record whose response carries a
            #     list of options the user must choose from (e.g.
            #     ``getProductInfo`` exposes ``$.itmInfo[*].itmNo`` —
            #     the available SKUs). In that case, defer to the caller
            #     to fetch options and pop up a question, instead of
            #     chaining the producer in and binding ``[0]`` blindly.
            #
            #     Constrained to ``canonical_action='read'`` because
            #     ``search`` producers (e.g. seltSearchProduct → goodsNo)
            #     are exactly the chain idiom we DO want — pick the first
            #     hit and continue. Without this constraint legitimate
            #     search→detail chains turn into popups.
            producer_action = self._producer_action(producer)
            if (
                producer_action == "read"
                and self._is_producer_simple_callable(producer, entities)
            ):
                opt_path = self._produces_path_for(
                    producer, semantic=semantic, field_name=field_name,
                )
                if opt_path and "[*]" in opt_path:
                    raise DynamicOptionRequired(
                        f"tool {tool_name!r} requires {field_name!r} "
                        f"(semantic={semantic!r}) — dynamic option from "
                        f"{producer!r}; caller should fetch options and "
                        f"prompt the user",
                        field_name=field_name,
                        semantic_tag=semantic,
                        producer_name=producer,
                        options_path=opt_path,
                        label_field_hints=self._label_hints_for(producer, opt_path),
                    )

            # Recurse into the producer first so step_id ordering is correct.
            # Cycle policy B + F2: if the producer's own chain is too deep
            # or cycles back, we don't abort the whole plan — we drop this
            # producer and fall back to a user_input slot for the field.
            # This keeps the surface tool callable when the prerequisite
            # chain extends beyond what the synthesiser can flatten.
            try:
                self._resolve(
                    tool_name=producer,
                    entities=entities,
                    steps_by_tool=steps_by_tool,
                    visiting=visiting,
                    depth=depth + 1,
                )
            except (MaxDepthExceededError, CyclicDependencyError) as exc:
                placeholder = f"${{user_input.{field_name}}}"
                args[field_name] = placeholder
                rationales.append(
                    f"{field_name} ← user_input (chain unflattenable: {exc.__class__.__name__})"
                )
                continue

            # Build a placeholder binding — will be rewritten after step_ids
            # are assigned. Format: ${<tool_name>.<jsonpath-sans-root>}
            prod_path = self._producer_jsonpath(producer, semantic, field_name)
            args[field_name] = f"${{{producer}.{prod_path}}}"
            rationales.append(f"{field_name} ← {producer} ({prod_path})")

        steps_by_tool[tool_name] = _PartialStep(
            tool=tool_name,
            args=args,
            rationale="; ".join(rationales) if rationales else "",
        )
        visiting.discard(tool_name)
        return tool_name

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_producer_indexes(self) -> None:
        """Index which tools produce which semantic / field across the graph.

        Echo-back filter: a tool that takes ``ordNo`` as input and echoes it
        back in its response is NOT a producer of ``ordNo`` in any useful
        sense — it's just relaying the value the caller already supplied. We
        skip those entries so the index reflects tools that actually CREATE
        or DISCOVER the value (``listOrders``, ``createOrder``,
        ``searchOrders`` etc.) rather than every endpoint that happens to
        round-trip the field.

        Same rule applied to ``semantic_tag`` for parity with the LLM Pass 2
        enrichment path. Empty consumes (no input fields) → never echo, so
        all produces are real producers.
        """
        for name, tool in self._tools.items():
            meta = tool.get("metadata") or {}
            consumed_fields: set[str] = set()
            consumed_semantics: set[str] = set()
            for c in meta.get("consumes") or []:
                if not isinstance(c, dict):
                    continue
                cf = c.get("field_name") or ""
                cs = c.get("semantic_tag") or ""
                if cf:
                    consumed_fields.add(cf)
                if cs:
                    consumed_semantics.add(cs)

            for produce in meta.get("produces") or []:
                sem = produce.get("semantic_tag") or ""
                fname = produce.get("field_name") or ""
                # Skip pure echo-back: the field came in, gets relayed out.
                if fname and fname in consumed_fields:
                    continue
                if sem and sem in consumed_semantics:
                    continue
                if sem:
                    self._producers_by_semantic.setdefault(sem, []).append(name)
                if fname:
                    self._producers_by_field.setdefault(fname, []).append(name)
                    loose = _normalize_field_name(fname)
                    if loose and loose != fname:
                        self._producers_by_loose_field.setdefault(loose, []).append(name)

    # ---- graphify edge indexing & traversal ---------------------------------

    _WORKFLOW_RELATIONS: frozenset[str] = frozenset(
        {"requires", "precedes", "complementary"}
    )
    _CONFIDENCE_RANK: dict[str, int] = {
        "EXTRACTED": 0,
        "INFERRED": 1,
        "AMBIGUOUS": 2,
    }

    def _index_workflow_edges(self, graph: dict[str, Any]) -> None:
        """Bucket the graphify graph's outgoing workflow edges by source tool.

        Accepts the same graph dict the rest of the class consumes — looks
        for ``graph.graph.edges`` (DictGraph.to_dict() output) or the
        legacy NetworkX-style ``graph.graph.links`` if present. Edges
        without a confidence label are kept (treated as fallback) so this
        also works on graphs built before the graphify ingest landed.
        """
        graph_inner = graph.get("graph") or {}
        edges = graph_inner.get("edges") or graph_inner.get("links") or []
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = e.get("source") or e.get("from")
            tgt = e.get("target") or e.get("to")
            rel = e.get("relation")
            rel_str = (
                rel.value if hasattr(rel, "value")
                else str(rel) if rel is not None else ""
            ).lower()
            if not src or not tgt or rel_str not in self._WORKFLOW_RELATIONS:
                continue
            self._workflow_edges_out.setdefault(src, []).append({
                "target": tgt,
                "relation": rel_str,
                "confidence": e.get("confidence"),
                "conf_score": float(e.get("conf_score") or 0.0),
                "evidence": e.get("evidence") or "",
            })

    # Producer-signal score weights. Higher = stronger signal that this
    # candidate genuinely produces the value the target needs. Weights chosen
    # so combined signals (e.g. graph EXTRACTED + field exact = 90) beat any
    # single signal, and graph EXTRACTED alone (50) beats field exact alone
    # (40) — Path/$ref/CRUD-derived edges are more reliable than coincidental
    # field-name overlap. ``semantic_exact`` requires LLM Pass 2 enrichment;
    # when present it's the strongest signal we have.
    _SIGNAL_WEIGHTS: dict[str, int] = {
        "semantic_exact": 100,
        "graph_EXTRACTED": 50,
        "field_exact": 40,
        "graph_INFERRED": 20,
        "field_loose": 10,
        "graph_AMBIGUOUS": 5,
    }

    def _find_producer(
        self,
        *,
        semantic: str,
        field_name: str,
        target_tool: str,
        entities: dict[str, Any],
        excluded: set[str] | None = None,
    ) -> str | None:
        """Pick the best producer using combined graph + schema signals.

        Producer matching is treated as the intersection of two first-class
        signals (NOT a fallback chain):
          (a) Schema match — semantic_tag / field_name on ``produces``.
          (b) Graph traversal — outgoing REQUIRES / PRECEDES / COMPLEMENTARY
              edges from ``target_tool``, ranked by ``confidence``.

        A candidate accumulates one entry per matching signal. The signal
        weights live in ``_SIGNAL_WEIGHTS`` and combine additively, so a
        candidate matched by both graph EXTRACTED and field_exact (90) wins
        over one matched only by field_exact (40). Tie-break uses the
        existing Pass-2 ``_rank_producers`` (entity affinity, pair hint,
        canonical action), and ``_is_chain_eligible`` still gates the final
        pick — sparse Pass-2 metadata pass-throughs apply unchanged.

        ``excluded`` is the set of tools currently being resolved (the
        caller's ``visiting`` set). Producer candidates in this set would
        re-enter recursion and trigger ``CyclicDependencyError`` — we skip
        them here so the second-best candidate gets a chance instead. This
        is the "skip-this-branch" cycle policy: the chain reroutes around
        the cycle when alternative producers exist; only when all candidates
        cycle does the caller fall back to user-input slot handling.

        Returns the highest-scoring eligible candidate, or None if no
        candidate has any signal (or all signals point to ``excluded`` tools).
        """
        excluded = excluded or set()
        candidate_signals: dict[str, set[str]] = {}

        def _record(name: str, signal: str) -> None:
            if name and name != target_tool:
                candidate_signals.setdefault(name, set()).add(signal)

        # (a) schema-side: exact semantic / field_name (echo-back already
        # filtered when the index was built).
        if semantic:
            for n in self._producers_by_semantic.get(semantic, []):
                _record(n, "semantic_exact")
        if field_name:
            for n in self._producers_by_field.get(field_name, []):
                _record(n, "field_exact")

        # (a') schema-side: loose field match — separator/case folded.
        # ``ordNo`` won't match ``orderNo`` (different roots) but will match
        # ``ord_no`` / ``ORDNO``. Cross-naming-convention safety net.
        if field_name:
            loose = _normalize_field_name(field_name)
            if loose:
                for n in self._producers_by_loose_field.get(loose, []):
                    if n in candidate_signals:
                        continue  # already had a stronger signal
                    _record(n, "field_loose")

        # (b) graph-side: walk outgoing workflow edges, verify each
        # candidate actually has a matching produces entry.
        edges = self._workflow_edges_out.get(target_tool) or []
        loose_target = _normalize_field_name(field_name) if field_name else ""
        for e in edges:
            cand = e.get("target")
            if not cand or cand == target_tool:
                continue
            tool = self._tools.get(cand)
            if not tool:
                continue
            cand_consumes_fields = {
                (c or {}).get("field_name", "")
                for c in (tool.get("metadata") or {}).get("consumes") or []
                if isinstance(c, dict)
            }
            cand_consumes_semantics = {
                (c or {}).get("semantic_tag", "")
                for c in (tool.get("metadata") or {}).get("consumes") or []
                if isinstance(c, dict)
            }
            for p in (tool.get("metadata") or {}).get("produces") or []:
                if not isinstance(p, dict):
                    continue
                p_sem = p.get("semantic_tag") or ""
                p_fname = p.get("field_name") or ""
                # Echo-back guard for the candidate itself — same rule as
                # _build_producer_indexes, applied here so graph-edge
                # discoveries don't sneak in a relayed value.
                if p_fname and p_fname in cand_consumes_fields:
                    continue
                if p_sem and p_sem in cand_consumes_semantics:
                    continue

                matched = False
                if semantic and p_sem == semantic:
                    matched = True
                elif field_name and p_fname == field_name:
                    matched = True
                elif loose_target and _normalize_field_name(p_fname) == loose_target:
                    matched = True
                if not matched:
                    continue

                conf = e.get("confidence") or "AMBIGUOUS"
                _record(cand, f"graph_{conf}")
                break  # one signal per candidate per edge target is enough

        if not candidate_signals:
            return None

        # Score and pre-rank by signal strength (stable for equal scores).
        def _score(signals: set[str]) -> int:
            return sum(self._SIGNAL_WEIGHTS.get(s, 0) for s in signals)

        scored = sorted(
            candidate_signals.items(),
            key=lambda item: (-_score(item[1]), item[0]),
        )
        sorted_names = [n for n, _ in scored]

        # Pass 2 / chain-eligibility gate — pass-through when ai_metadata
        # is sparse, identical behaviour to the previous implementation.
        # Cycle filter: skip candidates currently in the resolution stack so
        # the synthesiser reroutes around the cycle instead of raising.
        ranked = self._rank_producers(
            sorted_names, target_tool=target_tool, entities=entities,
        )
        for cand in ranked:
            if cand in excluded:
                continue
            if self._is_chain_eligible(cand, target_tool=target_tool):
                return cand
        return None

    def _producer_action(self, producer_name: str) -> str:
        """Return the producer's ``ai_metadata.canonical_action`` (lowercased,
        empty string if missing). Used to gate dynamic-option popups to
        ``read`` producers — search producers are the chain idiom (pick
        first hit), not popup candidates.
        """
        tool = self._tools.get(producer_name) or {}
        ai = (tool.get("metadata") or {}).get("ai_metadata") or {}
        return str(ai.get("canonical_action") or "").strip().lower()

    def _is_producer_simple_callable(
        self,
        producer_name: str,
        entities: dict[str, Any],
    ) -> bool:
        """True iff the producer can be called with only the user's entities
        and the collection's context_defaults — i.e. no further producer
        chain needed to source its inputs.

        Used to detect "single-hop dynamic option" cases: instead of
        chaining the producer into the plan, the caller fetches it once
        and pops up the resulting list to the user (e.g. itmNo from
        getProductInfo when the user already supplied goodsNo).
        """
        producer = self._tools.get(producer_name) or {}
        for c in (producer.get("metadata") or {}).get("consumes") or []:
            if not isinstance(c, dict) or not c.get("required"):
                continue
            field = c.get("field_name") or ""
            sem = c.get("semantic_tag") or ""
            kind = str(c.get("kind") or "data").strip().lower()
            if self._match_entity(entities, sem, field) is not None:
                continue
            if kind == "context" and self._lookup_context_default(sem, field) is not None:
                continue
            return False
        return True

    def _produces_path_for(
        self,
        producer_name: str,
        *,
        semantic: str,
        field_name: str,
    ) -> str:
        """Find the producer's json_path that emits the given field — the
        location of the option array in the response (e.g.
        ``$.itmInfo[*].itmNo``). Empty string if no match.
        """
        producer = self._tools.get(producer_name) or {}
        for p in (producer.get("metadata") or {}).get("produces") or []:
            if not isinstance(p, dict):
                continue
            if semantic and p.get("semantic_tag") == semantic:
                return str(p.get("json_path") or "")
        # Fallback: match by field_name when semantic missing/mismatched
        for p in (producer.get("metadata") or {}).get("produces") or []:
            if not isinstance(p, dict):
                continue
            if field_name and p.get("field_name") == field_name:
                return str(p.get("json_path") or "")
        return ""

    def _label_hints_for(
        self,
        producer_name: str,
        options_path: str,
    ) -> list[str]:
        """Return field names that look like human labels living next to
        the option-code field in the producer's response. Heuristic: same
        array prefix, name ending in ``Nm`` / ``Name`` / ``Label``.

        ``options_path`` looks like ``$.itmInfo[*].itmNo``; we walk the
        producer's other produces entries that share the prefix
        ``$.itmInfo[*].`` and pick the ones whose field_name suggests a
        label.
        """
        producer = self._tools.get(producer_name) or {}
        # Compute the array prefix: everything up to the last "."
        if "." not in options_path:
            return []
        prefix = options_path.rsplit(".", 1)[0] + "."
        hints: list[str] = []
        seen: set[str] = set()
        for p in (producer.get("metadata") or {}).get("produces") or []:
            if not isinstance(p, dict):
                continue
            jp = str(p.get("json_path") or "")
            if not jp.startswith(prefix):
                continue
            field = str(p.get("field_name") or "")
            if not field or field in seen:
                continue
            lower = field.lower()
            if lower.endswith("nm") or lower.endswith("name") or lower.endswith("label"):
                hints.append(field)
                seen.add(field)
        return hints

    def _is_chain_eligible(self, producer_name: str, *, target_tool: str) -> bool:
        """Return True if ``producer_name`` may be added to the prerequisite
        chain for ``target_tool``.

        Two signals from Pass 2 ``ai_metadata`` decide:

          1. ``canonical_action`` ∈ {search, read}
             create/update/delete/action are not prerequisite material —
             they perform side effects, never just data lookup.
          2. ``primary_resource`` is in the target's domain set
             (target's own resource + the prefix of every consume's
             semantic_tag, e.g. ``product_id`` ⇒ ``product``).

        Either signal absent (sparse ``ai_metadata``) ⇒ pass through.
        Operators that haven't enriched the graph yet keep the previous
        behaviour; once enriched, the policy starts filtering. Also
        reverts to pass-through if the target itself has no ``ai_metadata``,
        because the "domain set" can't be computed.
        """
        producer = self._tools.get(producer_name) or {}
        p_meta = (producer.get("metadata") or {}).get("ai_metadata") or {}
        p_action = str(p_meta.get("canonical_action") or "").strip().lower()
        if not p_action:
            return True
        if p_action not in ("search", "read"):
            return False

        p_resource = str(p_meta.get("primary_resource") or "").strip().lower()
        if not p_resource:
            return True

        target = self._tools.get(target_tool) or {}
        t_meta_full = target.get("metadata") or {}
        t_meta = t_meta_full.get("ai_metadata") or {}
        t_resource = str(t_meta.get("primary_resource") or "").strip().lower()

        related: set[str] = set()
        if t_resource:
            related.add(t_resource)
            if "_" in t_resource:
                related.add(t_resource.split("_", 1)[0])

        for c in (t_meta_full.get("consumes") or []):
            if not isinstance(c, dict):
                continue
            sem = str(c.get("semantic_tag") or "").strip().lower()
            if not sem:
                continue
            related.add(sem.split("_", 1)[0] if "_" in sem else sem)

        if not related:
            return True

        p_prefix = p_resource.split("_", 1)[0] if "_" in p_resource else p_resource
        return p_resource in related or p_prefix in related

    def _rank_producers(
        self,
        candidates: list[str],
        *,
        target_tool: str,
        entities: dict[str, Any],
    ) -> list[str]:
        """Rank candidates by Pass 2 metadata signals.

        Order:
          1. Entity affinity — producer consumes a field the user already
             supplied (so the chain actually uses user input).
          2. Pair hint — target's ``pairs_well_with`` names this producer.
          3. Action preference — ``search`` > ``read`` > others as a
             prerequisite role.
        Ties fall back to insertion order (stable sort).

        No hardcoded names / regexes. Every signal is a per-tool Pass 2
        field the LLM filled at ingest time.
        """
        target_meta = (self._tools.get(target_tool) or {}).get("metadata") or {}
        target_ai = target_meta.get("ai_metadata") or {}
        pair_names = {
            str(p.get("tool") or "").strip()
            for p in (target_ai.get("pairs_well_with") or [])
            if isinstance(p, dict)
        }
        pair_names.discard("")
        entity_keys = {str(k) for k in (entities or {}).keys()}

        action_score = {"search": 3, "read": 2, "action": 1}

        def _score(name: str) -> tuple[int, int, int]:
            tool = self._tools.get(name) or {}
            meta = tool.get("metadata") or {}
            ai = meta.get("ai_metadata") or {}

            affinity = 0
            for c in (meta.get("consumes") or []):
                tag = c.get("semantic_tag") or ""
                fname = c.get("field_name") or ""
                if (tag and tag in entity_keys) or (fname and fname in entity_keys):
                    affinity += 1

            pair_bonus = 1 if name in pair_names else 0
            action = str(ai.get("canonical_action") or "").strip().lower()
            return (affinity, pair_bonus, action_score.get(action, 0))

        # Python's sort is stable; higher score wins, ties keep insertion order.
        return sorted(candidates, key=_score, reverse=True)

    def _response_root_keys(self, tool_name: str) -> list[str]:
        """Top-level keys of the tool's response, taken from ``produces``.

        Each ``produces[].json_path`` (e.g. ``$.searchDataList[*].goodsNo``)
        contributes its first dotted segment (``searchDataList``). Used by
        PlanRunner as a schema hint for envelope detection — when the
        actual response is missing every hint at root but a single nested
        dict contains them, the wrapper is peeled away.
        """
        tool = self._tools.get(tool_name) or {}
        produces = (tool.get("metadata") or {}).get("produces") or []
        out: list[str] = []
        seen: set[str] = set()
        for p in produces:
            raw = p.get("json_path") or ""
            head = _jsonpath_head(raw)
            if head and head not in seen:
                out.append(head)
                seen.add(head)
        return out

    def _producer_jsonpath(
        self,
        producer: str,
        semantic: str,
        field_name: str,
    ) -> str:
        """Return a dotted path under the producer's response that yields
        the desired field. Converts ``$.a.b[*].c`` → ``a.b[0].c`` (v1 picks
        the first array element when a wildcard is present).

        Falls back to ``body`` + field_name if we can't locate the produces.
        """
        tool = self._tools.get(producer) or {}
        produces = (tool.get("metadata") or {}).get("produces") or []
        match = None
        if semantic:
            match = next(
                (p for p in produces if p.get("semantic_tag") == semantic),
                None,
            )
        if match is None and field_name:
            match = next(
                (p for p in produces if p.get("field_name") == field_name),
                None,
            )
        if match is None:
            return f"body.{field_name}" if field_name else "body"

        raw = match.get("json_path") or ""
        return _normalize_jsonpath_for_binding(raw)

    def _lookup_context_default(
        self,
        semantic: str,
        field_name: str,
    ) -> Any | None:
        """Pick a registered context default for a consume field.

        Mirrors ``_match_entity`` lookup order — semantic tag first (Pass 2
        canonical id), field name second (Pass 1 raw). Returns ``None`` if
        the operator hasn't registered a value for either key.
        """
        if not self._context_defaults:
            return None
        if semantic and semantic in self._context_defaults:
            return self._context_defaults[semantic]
        if field_name and field_name in self._context_defaults:
            return self._context_defaults[field_name]
        return None

    def _match_entity(
        self,
        entities: dict[str, Any],
        semantic: str,
        field_name: str,
    ) -> Any | None:
        """Look up user-supplied entity by semantic tag or field name."""
        if semantic and semantic in entities:
            return entities[semantic]
        if field_name and field_name in entities:
            return entities[field_name]
        return None

    def _rewrite_tool_refs(
        self,
        value: Any,
        steps_by_tool: dict[str, _PartialStep],
    ) -> Any:
        """Recursively rewrite ``${<tool_name>.<path>}`` → ``${sN.<path>}``."""
        if isinstance(value, dict):
            return {k: self._rewrite_tool_refs(v, steps_by_tool) for k, v in value.items()}
        if isinstance(value, list):
            return [self._rewrite_tool_refs(v, steps_by_tool) for v in value]
        if not isinstance(value, str):
            return value
        # Only rewrite full-string bindings that we inserted. Entities
        # supplied by the caller are left alone (no ${...} wrapping).
        if not (value.startswith("${") and value.endswith("}")):
            return value
        inner = value[2:-1]
        head, _, tail = inner.partition(".")
        if head in steps_by_tool:
            step_id = steps_by_tool[head].step_id
            rest = f".{tail}" if tail else ""
            return f"${{{step_id}{rest}}}"
        return value


def _jsonpath_head(raw: str) -> str:
    """First dotted segment of a JSONPath, stripping ``$``, ``.`` and ``[…]``.

    ``$.payload.searchDataList[*].goodsNo`` → ``"payload"``.
    ``$.totalCount`` → ``"totalCount"``.
    Returns ``""`` for empty / unparseable input.
    """
    if not raw:
        return ""
    path = raw[1:] if raw.startswith("$") else raw
    if path.startswith("."):
        path = path[1:]
    # Cut at the first separator (``.`` or ``[``).
    for i, ch in enumerate(path):
        if ch in ".[":
            return path[:i]
    return path


def _normalize_jsonpath_for_binding(raw: str) -> str:
    """``$.body.goods[*].goodsNo`` → ``body.goods[0].goodsNo``.

    v1 always picks index 0 for arrays. Fan-out is v2 (design §11.1).
    """
    if not raw:
        return ""
    path = raw
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    return path.replace("[*]", "[0]")


__all__ = [
    "PathSynthesizer",
    "PlanSynthesisError",
    "UnsatisfiableFieldError",
    "CyclicDependencyError",
    "MaxDepthExceededError",
    "DynamicOptionRequired",
]
