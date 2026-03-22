"""Workflow planning: build multi-step tool chains from graph structure + optional LLM.

Usage::

    # Graph-only (zero-dep, fast)
    plan = tg.plan_workflow("process a refund")
    for step in plan.steps:
        print(f"{step.order}. {step.tool.name} — {step.reason}")

    # Manual editing
    plan.insert_step(0, "getOrder", reason="need order ID first")
    plan.remove_step("listOrders")
    plan.reorder(["getOrder", "requestRefund"])

    # Save / Load
    plan.save("refund_workflow.json")
    plan = WorkflowPlan.load("refund_workflow.json", tools=tg.tools)

    # Graph + LLM (fills cross-resource gaps)
    plan = tg.plan_workflow("process a refund", llm=my_llm)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from graph_tool_call.core.protocol import GraphEngine
from graph_tool_call.core.tool import ToolSchema
from graph_tool_call.ontology.schema import NodeType


@dataclass
class WorkflowStep:
    """A single step in a workflow chain."""

    order: int
    tool: ToolSchema
    reason: str = ""
    params_from: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "tool": self.tool.name,
            "reason": self.reason,
            "params_from": dict(self.params_from),
        }


@dataclass
class WorkflowPlan:
    """A planned multi-step workflow with manual editing support."""

    goal: str
    steps: list[WorkflowStep] = field(default_factory=list)
    confidence: str = "graph"  # "graph" | "graph+llm" | "manual"

    @property
    def tool_names(self) -> list[str]:
        return [s.tool.name for s in self.steps]

    def __repr__(self) -> str:
        steps_str = " → ".join(s.tool.name for s in self.steps)
        return f"WorkflowPlan({self.goal!r}, [{steps_str}])"

    # --- Manual editing ---

    def insert_step(
        self,
        position: int,
        tool: ToolSchema | str,
        *,
        reason: str = "manually added",
        tools: dict[str, ToolSchema] | None = None,
    ) -> WorkflowPlan:
        """Insert a step at the given position. Returns self for chaining.

        Args:
            position: 0-based index. Negative indexes work like list.insert.
            tool: ToolSchema object or tool name string.
            reason: Why this step was added.
            tools: Tool registry (required if tool is a string).
        """
        if isinstance(tool, str):
            if not tools:
                raise ValueError("tools dict required when tool is a string")
            tool_obj = tools.get(tool)
            if not tool_obj:
                raise KeyError(f"Tool {tool!r} not found")
            tool = tool_obj

        step = WorkflowStep(order=0, tool=tool, reason=reason)
        self.steps.insert(position, step)
        self._renumber()
        self.confidence = "manual"
        return self

    def remove_step(self, tool_name: str) -> WorkflowPlan:
        """Remove a step by tool name. Returns self for chaining."""
        self.steps = [s for s in self.steps if s.tool.name != tool_name]
        self._renumber()
        self.confidence = "manual"
        return self

    def reorder(self, tool_names: list[str]) -> WorkflowPlan:
        """Reorder steps to match the given tool name sequence.

        Tools not in the list are dropped. Returns self for chaining.
        """
        by_name = {s.tool.name: s for s in self.steps}
        self.steps = [by_name[n] for n in tool_names if n in by_name]
        self._renumber()
        self.confidence = "manual"
        return self

    def set_param_mapping(
        self, tool_name: str, param: str, source: str
    ) -> WorkflowPlan:
        """Set a parameter mapping for a step.

        Example::
            plan.set_param_mapping("requestRefund", "order_id", "getOrder.response.id")
        """
        for step in self.steps:
            if step.tool.name == tool_name:
                step.params_from[param] = source
                break
        return self

    def _renumber(self) -> None:
        for i, step in enumerate(self.steps):
            step.order = i + 1

    # --- Serialization ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "confidence": self.confidence,
            "steps": [s.to_dict() for s in self.steps],
        }

    def save(self, path: str | Path) -> None:
        """Save workflow to JSON file."""
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def open_editor(self, tools: dict[str, ToolSchema] | None = None) -> None:
        """Open the visual workflow editor in the default browser.

        Passes the current workflow + available tools to the editor.

        Example::
            plan = tg.plan_workflow("process a refund")
            plan.open_editor(tools=tg.tools)
        """
        import tempfile
        import urllib.parse
        import webbrowser

        # Build editor data: workflow + tool catalog
        tool_catalog = {}
        if tools:
            for name, tool in tools.items():
                meta = tool.metadata or {}
                tool_catalog[name] = {
                    "description": tool.description or "",
                    "method": meta.get("method", ""),
                }

        data = {
            "goal": self.goal,
            "confidence": self.confidence,
            "steps": [s.to_dict() for s in self.steps],
            "tools": tool_catalog,
        }

        # Copy editor HTML and inject data
        editor_path = Path(__file__).parent / "static" / "workflow_editor.html"
        if not editor_path.exists():
            raise FileNotFoundError(f"Editor not found: {editor_path}")

        html = editor_path.read_text(encoding="utf-8")
        # Inject data via script tag before </body>
        inject = f"""<script>
try {{
  const _initData = {json.dumps(data, ensure_ascii=False)};
  if (_initData.goal) document.getElementById('goalInput').value = _initData.goal;
  if (_initData.steps) steps = _initData.steps;
  if (_initData.tools) {{ allTools = _initData.tools; renderToolList(); }}
  render();
}} catch(e) {{ console.error('Init error:', e); }}
</script>"""
        html = html.replace("</body>", inject + "\n</body>")

        # Write to temp file and open
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(html)
            webbrowser.open(f"file://{f.name}")

    @classmethod
    def load(
        cls, path: str | Path, *, tools: dict[str, ToolSchema]
    ) -> WorkflowPlan:
        """Load workflow from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        steps = []
        for s in data.get("steps", []):
            tool = tools.get(s["tool"])
            if not tool:
                continue
            steps.append(WorkflowStep(
                order=s.get("order", 0),
                tool=tool,
                reason=s.get("reason", ""),
                params_from=s.get("params_from", {}),
            ))
        plan = cls(
            goal=data.get("goal", ""),
            steps=steps,
            confidence=data.get("confidence", "loaded"),
        )
        plan._renumber()
        return plan


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
        max_steps: int = 6,
        top_k: int = 5,
    ) -> WorkflowPlan:
        """Plan a workflow for the given goal.

        1. Find the target tool via resource-first search + name matching
        2. Find same-category prerequisites (GET methods that provide IDs)
        3. Topological sort for execution order
        4. If LLM provided, fill cross-resource gaps
        """
        from graph_tool_call.retrieval.graph_search import GraphSearcher
        from graph_tool_call.retrieval.intent import classify_intent

        searcher = GraphSearcher(self._graph)
        intent = classify_intent(goal)

        # Step 1: Find target tool
        resource_scores = searcher.resource_first_search(
            goal, intent=intent, max_results=top_k, tools=self._tools
        )
        if not resource_scores:
            resource_scores = self._name_match(goal)
        if not resource_scores:
            return WorkflowPlan(goal=goal)

        primary_tool = self._pick_primary(goal, resource_scores)

        # Step 2: Build focused chain
        chain = self._build_chain(primary_tool, max_steps)

        # Step 3: Topological sort → steps
        ordered = self._topo_sort(chain)
        steps = []
        for i, tool_name in enumerate(ordered):
            tool = self._tools.get(tool_name)
            if not tool:
                continue
            reason = self._infer_reason(tool_name, primary_tool, chain)
            steps.append(WorkflowStep(order=i + 1, tool=tool, reason=reason))

        plan = WorkflowPlan(goal=goal, steps=steps, confidence="graph")

        # Step 4: LLM enhancement
        if llm is not None and steps:
            plan = self._enhance_with_llm(plan, llm, max_steps)

        return plan

    def _pick_primary(self, goal: str, scores: dict[str, float]) -> str:
        """Pick the best primary tool by combining graph score + name relevance."""
        tokens = set(re.split(r"[\s_\-/.,;:!?()]+", goal.lower()))
        tokens -= {"a", "an", "the", "of", "for", "to", "in", "by", "is",
                    "and", "or", "my", "all", "this", "that", "with", "from"}
        tokens.discard("")

        def _relevance(name: str) -> float:
            parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            name_tokens = set(re.split(r"[\s_\-/]+", parts.lower()))
            overlap = len(tokens & name_tokens)
            # Also check description
            tool = self._tools.get(name)
            desc_hits = 0
            if tool and tool.description:
                desc_lower = tool.description.lower()
                desc_hits = sum(1 for t in tokens if t in desc_lower)
            return overlap * 2 + desc_hits

        ranked = sorted(
            scores.items(),
            key=lambda x: (x[1], _relevance(x[0])),
            reverse=True,
        )
        return ranked[0][0]

    def _name_match(self, goal: str) -> dict[str, float]:
        """Simple name-based matching as fallback."""
        tokens = set(re.split(r"[\s_\-/.,;:!?()]+", goal.lower()))
        tokens -= {"a", "an", "the", "of", "for", "to", "in", "by", "is", "and", "or"}
        tokens.discard("")

        scores: dict[str, float] = {}
        for name in self._tools:
            parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            name_tokens = set(re.split(r"[\s_\-/]+", parts.lower()))
            overlap = len(tokens & name_tokens)
            if overlap > 0:
                scores[name] = overlap
        return scores

    def _build_chain(
        self, target: str, max_steps: int
    ) -> dict[str, set[str]]:
        """Build a focused prerequisite chain for the target tool.

        Rules:
        1. Only follow direct REQUIRES edges from the target
        2. Only include prerequisites that are data providers (GET/LIST)
           in the SAME category as the target
        3. Hard cap at max_steps

        This prevents chain explosion from loose cross-resource REQUIRES.
        """
        predecessors: dict[str, set[str]] = defaultdict(set)
        predecessors[target] = set()

        if not self._graph.has_node(target):
            return dict(predecessors)

        # Find target's category
        target_category = self._get_category(target)

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
            neighbor_category = self._get_category(neighbor)
            n_method = ""
            if neighbor_tool.metadata:
                n_method = neighbor_tool.metadata.get("method", "").upper()

            # REQUIRES: only accept same-category GET/LIST as prerequisite
            if "REQUIRES" in relation and src == target:
                same_cat = (
                    target_category
                    and neighbor_category
                    and target_category == neighbor_category
                )
                is_getter = n_method == "GET" or any(
                    v in neighbor.lower() for v in ("get", "list", "read")
                )
                if same_cat and is_getter:
                    predecessors[target].add(neighbor)
                    if neighbor not in predecessors:
                        predecessors[neighbor] = set()

            # PRECEDES: something comes before target (only POST/create)
            elif "PRECEDES" in relation and tgt == target:
                same_cat = (
                    target_category
                    and neighbor_category
                    and target_category == neighbor_category
                )
                is_creator = n_method == "POST" or any(
                    v in neighbor.lower() for v in ("create", "add")
                )
                if same_cat and is_creator:
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

    def _get_category(self, tool_name: str) -> str | None:
        """Get the category node this tool belongs to."""
        if not self._graph.has_node(tool_name):
            return None
        for edge in self._graph.get_edges_from(tool_name, direction="out"):
            _, tgt, attrs = edge
            if "BELONGS_TO" in str(attrs.get("relation", "")):
                tgt_attrs = self._graph.get_node_attrs(tgt)
                if tgt_attrs.get("node_type") == NodeType.CATEGORY:
                    return tgt
        return None

    def _topo_sort(self, predecessors: dict[str, set[str]]) -> list[str]:
        """Kahn's algorithm for topological sort."""
        in_degree: dict[str, int] = {n: len(p) for n, p in predecessors.items()}
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
        for n in predecessors:
            if n not in result:
                result.append(n)
        return result

    def _infer_reason(
        self, tool_name: str, primary: str, chain: dict[str, set[str]]
    ) -> str:
        if tool_name == primary:
            return "primary action"
        dependents = [n for n, p in chain.items() if tool_name in p]
        if dependents:
            return f"prerequisite for {', '.join(dependents)}"
        return "related"

    def _enhance_with_llm(
        self, plan: WorkflowPlan, llm: Any, max_steps: int
    ) -> WorkflowPlan:
        """Use LLM to fill cross-resource gaps and add parameter mappings."""
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

        prompt = f"""Given a user's goal and a partial workflow chain from API structure,
complete the workflow by filling missing steps and adding parameter mappings.

Goal: {plan.goal}

Current chain (from graph): {json.dumps(current_chain)}

Available tools:
{chr(10).join(available[:60])}

Return JSON:
{{"steps": [{{"tool": "name", "reason": "why", "params_from": {{"param": "step.response.field"}}}}]}}

Rules:
- Keep existing chain steps unless clearly wrong
- Add missing steps if needed
- Maximum {max_steps} steps
- Order by execution sequence
"""
        try:
            response = llm.complete(prompt)
            text = response.text if hasattr(response, "text") else str(response)
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                return plan
            data = json.loads(json_match.group())
            llm_steps = data.get("steps", [])
            if not llm_steps:
                return plan
            new_steps = []
            for i, s in enumerate(llm_steps[:max_steps]):
                tool = self._tools.get(s.get("tool", ""))
                if not tool:
                    continue
                new_steps.append(WorkflowStep(
                    order=i + 1, tool=tool,
                    reason=s.get("reason", ""),
                    params_from=s.get("params_from", {}),
                ))
            if new_steps:
                plan.steps = new_steps
                plan.confidence = "graph+llm"
        except Exception:
            pass
        return plan
