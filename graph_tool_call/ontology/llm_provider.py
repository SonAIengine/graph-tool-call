"""LLM provider abstraction for ontology construction."""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from graph_tool_call.ontology.schema import RelationType


@dataclass
class ToolSummary:
    """Lightweight tool representation for LLM prompts."""

    name: str
    description: str
    parameters: list[str]  # just parameter names


@dataclass
class InferredRelation:
    """A relation inferred by an LLM."""

    source: str
    target: str
    relation_type: RelationType
    confidence: float
    reason: str


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_RELATION_PROMPT = """\
You are an API relationship analyzer. Given a list of API tools, \
identify relationships between them.

Tools:
{tools_list}

For each pair with a relationship, output a JSON array:
[
  {{"source": "toolA", "target": "toolB",
    "relation": "REQUIRES", "confidence": 0.9, "reason": "..."}}
]

Relation types: REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH
Only output the JSON array, nothing else."""

_CATEGORY_PROMPT = """\
Group these API tools into logical categories. Each tool should belong to exactly one category.

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


def _format_tools_list(tools: list[ToolSummary]) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        params = ", ".join(t.parameters) if t.parameters else "none"
        lines.append(f"{i}. {t.name} - {t.description} (params: {params})")
    return "\n".join(lines)


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
    """Extract JSON from LLM response text, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


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
        batch_size: int = 50,
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
    ) -> dict[str, list[str]]:
        """Suggest category groupings for tools."""
        prompt = _CATEGORY_PROMPT.format(tools_list=_format_tools_list(tools))
        response = self.generate(prompt)

        try:
            parsed = _extract_json(response)
            categories = parsed.get("categories", {})
            if isinstance(categories, dict):
                return {k: v for k, v in categories.items() if isinstance(v, list)}
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass

        return {}


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
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
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
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }
        ).encode()

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
