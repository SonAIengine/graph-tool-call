"""Workflow planning: build multi-step tool chains from graph structure + optional LLM.

Usage::

    # Graph-only (zero-dep, fast)
    chain = tg.plan_workflow("process a refund")
    for step in chain.steps:
        print(f"{step.order}. {step.tool.name} — {step.reason}")

    # Graph + LLM (fills cross-resource gaps)
    chain = tg.plan_workflow("process a refund", llm=my_llm)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType, RelationType


@dataclass
class WorkflowStep:
    """A single step in a workflow chain."""

    order: int
    tool: ToolSchema
    reason: str = ""
    params_from: dict[str, str] = field(default_factory=dict)
    # e.g., {"order_id": "getOrder.response.id"}


@dataclass
class WorkflowPlan:
    """A planned multi-step workflow."""

    goal: str
    steps: list[WorkflowStep] = field(default_factory=list)
    confidence: str = "graph"  # "graph" | "graph+llm"

    @property
    def tool_names(self) -> list[str]:
        return [s.tool.name for s in self.steps]

    def __repr__(self) -> str:
        steps_str = " → ".join(s.tool.name for s in self.steps)
        return f"WorkflowPlan({self.goal!r}, [{steps_str}])"


class WorkflowPlanner:
    """Builds multi-step tool chains from graph structure and optional LLM."""

    def __init__(
        self,
        graph: GraphEngine,
        tools: dict[str, ToolSchema],
    ) -> None:
        self._graph = graph
        self._tools = tools

    def plan(
        self,
        goal: str,
        *,
        llm: Any = None,
        max_steps: int = 8,
        top_k: int = 5,
    ) -> WorkflowPlan:
        """Plan a workflow for the given goal.

        1. Find the target tool(s) via resource-first graph search
        2. Expand REQUIRES/PRECEDES edges to build the chain
        3. Topological sort for execution order
        4. If LLM is provided, fill cross-resource gaps and add param mappings
        """
        from graph_tool_call.retrieval.graph_search import GraphSearcher
        from graph_tool_call.retrieval.intent import classify_intent

        searcher = GraphSearcher(self._graph)
        intent = classify_intent(goal)

        # Step 1: Find target tools
        resource_scores = searcher.resource_first_search(
            goal, intent=intent, max_results=top_k, tools=self._tools
        )

        if not resource_scores:
            # Fallback: BM25-style name matching
            resource_scores = self._name_match(goal)

        if not resource_scores:
            return WorkflowPlan(goal=goal)

        # Pick best target: prefer tools whose name matches query keywords
        query_tokens = set(re.split(r"[\s_\-/.,;:!?()]+", goal.lower()))
        query_tokens -= {"a", "an", "the", "of", "for", "to", "in", "by", "is", "and", "or", "my"}
        query_tokens.discard("")

        def _name_relevance(name: str) -> float:
            parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            name_tokens = set(re.split(r"[\s_\-/]+", parts.lower()))
            return len(query_tokens & name_tokens)

        ranked = sorted(
            resource_scores.items(),
            key=lambda x: (x[1], _name_relevance(x[0])),
            reverse=True,
        )
        primary_tool = ranked[0][0]

        # Step 2: Build chain via graph traversal
        chain_tools = self._build_chain(primary_tool, max_steps)

        # Step 3: Topological sort
        ordered = self._topo_sort(chain_tools)

        # Step 4: Build steps with reasons
        steps = []
        for i, tool_name in enumerate(ordered):
            tool = self._tools.get(tool_name)
            if not tool:
                continue
            reason = self._infer_reason(tool_name, primary_tool, chain_tools)
            steps.append(WorkflowStep(order=i + 1, tool=tool, reason=reason))

        plan = WorkflowPlan(goal=goal, steps=steps, confidence="graph")

        # Step 5: LLM enhancement (optional)
        if llm is not None and steps:
            plan = self._enhance_with_llm(plan, llm, max_steps)

        return plan

    def _name_match(self, goal: str) -> dict[str, float]:
        """Simple name-based matching as fallback."""
        tokens = set(re.split(r"[\s_\-/.,;:!?()]+", goal.lower()))
        tokens -= {"a", "an", "the", "of", "for", "to", "in", "by", "is", "and", "or"}
        tokens.discard("")

        scores: dict[str, float] = {}
        for name, tool in self._tools.items():
            # Split camelCase
            parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            name_tokens = set(re.split(r"[\s_\-/]+", parts.lower()))
            overlap = len(tokens & name_tokens)
            if overlap > 0:
                scores[name] = overlap
        return scores

    def _build_chain(
        self, target: str, max_steps: int
    ) -> dict[str, set[str]]:
        """Build a focused chain from the target tool's direct dependencies.

        Only follows REQUIRES edges backward (prerequisites) and PRECEDES
        edges forward (next steps) up to max_depth=1 from the target.
        This prevents chain explosion from transitive dependencies.

        Returns {tool_name: set of predecessors} for topo sort.
        """
        predecessors: dict[str, set[str]] = defaultdict(set)
        predecessors[target] = set()

        if not self._graph.has_node(target):
            return dict(predecessors)

        target_tool = self._tools.get(target)
        if not target_tool:
            return dict(predecessors)

        # Find prerequisites: tools that produce data this tool consumes
        # Strategy: look for tools that operate on the same resource
        # with read/list semantics (GET) when target needs an ID parameter
        target_params = set()
        if target_tool.parameters:
            for p in target_tool.parameters:
                p_name = p.name if hasattr(p, "name") else str(p)
                if "id" in p_name.lower() or "token" in p_name.lower():
                    target_params.add(p_name.lower())

        for edge in self._graph.get_edges_from(target, direction="both"):
            src, tgt, attrs = edge
            relation = str(attrs.get("relation", ""))
            neighbor = tgt if src == target else src

            n_attrs = self._graph.get_node_attrs(neighbor)
            if n_attrs.get("node_type") != NodeType.TOOL:
                continue
            if neighbor not in self._tools:
                continue

            neighbor_tool = self._tools[neighbor]

            # Only follow REQUIRES where the prerequisite is a data provider:
            # - GET/LIST methods that can provide IDs the target needs
            # - Same resource category (not random cross-resource deps)
            if "REQUIRES" in relation and src == target:
                n_method = ""
                if neighbor_tool.metadata:
                    n_method = neighbor_tool.metadata.get("method", "").upper()

                # Prerequisite should be a data-fetching operation
                is_data_provider = n_method in ("GET", "") or any(
                    v in neighbor.lower() for v in ("get", "list", "read", "find")
                )
                # Or shares a resource parameter with the target
                shares_resource = False
                if target_params and neighbor_tool.parameters:
                    for p in neighbor_tool.parameters:
                        p_name = p.name if hasattr(p, "name") else str(p)
                        if "id" in p_name.lower():
                            shares_resource = True
                            break

                if is_data_provider or shares_resource:
                    predecessors[target].add(neighbor)
                    if neighbor not in predecessors:
                        predecessors[neighbor] = set()

            elif "PRECEDES" in relation and tgt == target:
                # Only accept if predecessor is a setup/create operation
                n_method = ""
                if neighbor_tool.metadata:
                    n_method = neighbor_tool.metadata.get("method", "").upper()
                is_setup = n_method in ("POST", "") or any(
                    v in neighbor.lower() for v in ("create", "add", "setup", "init")
                )
                if is_setup:
                    predecessors[target].add(neighbor)
                    if neighbor not in predecessors:
                        predecessors[neighbor] = set()

        # Trim to max_steps
        if len(predecessors) > max_steps:
            direct_preds = list(predecessors[target])[:max_steps - 1]
            trimmed: dict[str, set[str]] = {target: set(direct_preds)}
            for p in direct_preds:
                trimmed[p] = set()
            return trimmed

        return dict(predecessors)

    def _topo_sort(self, predecessors: dict[str, set[str]]) -> list[str]:
        """Kahn's algorithm for topological sort."""
        in_degree: dict[str, int] = {n: len(preds) for n, preds in predecessors.items()}
        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for n, preds in predecessors.items():
                if node in preds:
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        queue.append(n)

        # Append any remaining (cycle) nodes
        for n in predecessors:
            if n not in result:
                result.append(n)

        return result

    def _infer_reason(
        self, tool_name: str, primary: str, chain: dict[str, set[str]]
    ) -> str:
        """Generate a human-readable reason for this step."""
        if tool_name == primary:
            return "primary action"

        preds = chain.get(tool_name, set())
        # Is this tool a prerequisite for something?
        dependents = [n for n, p in chain.items() if tool_name in p]

        if dependents:
            return f"prerequisite for {', '.join(dependents)}"
        if preds:
            return f"follows {', '.join(preds)}"
        return "related"

    def _enhance_with_llm(
        self, plan: WorkflowPlan, llm: Any, max_steps: int
    ) -> WorkflowPlan:
        """Use LLM to fill cross-resource gaps and add parameter mappings.

        The LLM receives:
        - The goal
        - Current chain (from graph)
        - All available tools
        And returns a refined chain with parameter mappings.
        """
        # Build tool catalog for LLM
        current_chain = [s.tool.name for s in plan.steps]
        available = []
        for name, tool in self._tools.items():
            desc = tool.description or ""
            params = []
            if tool.parameters:
                for p in tool.parameters:
                    p_name = p.name if hasattr(p, "name") else str(p)
                    required = p.required if hasattr(p, "required") else False
                    params.append(f"{p_name}{'*' if required else ''}")
            param_str = f" (params: {', '.join(params)})" if params else ""
            available.append(f"- {name}: {desc}{param_str}")

        prompt = f"""Given a user's goal and a partial workflow chain discovered from API structure,
complete the workflow by filling any missing steps and adding parameter mappings.

Goal: {plan.goal}

Current chain (from graph structure):
{json.dumps(current_chain)}

Available tools:
{chr(10).join(available[:50])}

Return a JSON object with:
{{
  "steps": [
    {{
      "tool": "toolName",
      "reason": "why this step is needed",
      "params_from": {{"param_name": "previousStep.response.field"}}
    }}
  ]
}}

Rules:
- Keep all steps from the current chain unless clearly wrong
- Add missing steps between existing ones if needed
- Maximum {max_steps} steps
- params_from maps input parameters to outputs of previous steps
- Order steps by execution sequence
"""

        try:
            response = llm.complete(prompt)
            if hasattr(response, "text"):
                text = response.text
            elif isinstance(response, str):
                text = response
            else:
                return plan

            # Parse JSON from response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                return plan

            data = json.loads(json_match.group())
            llm_steps = data.get("steps", [])

            if not llm_steps:
                return plan

            new_steps = []
            for i, step_data in enumerate(llm_steps[:max_steps]):
                tool_name = step_data.get("tool", "")
                tool = self._tools.get(tool_name)
                if not tool:
                    continue
                new_steps.append(WorkflowStep(
                    order=i + 1,
                    tool=tool,
                    reason=step_data.get("reason", ""),
                    params_from=step_data.get("params_from", {}),
                ))

            if new_steps:
                plan.steps = new_steps
                plan.confidence = "graph+llm"

        except Exception:
            pass  # LLM enhancement is best-effort

        return plan
