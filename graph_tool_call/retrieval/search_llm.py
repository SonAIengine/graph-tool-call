"""LLM provider abstraction for search query enhancement."""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExpandedQuery:
    """Result of query expansion (Tier 1)."""

    keywords: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    english_terms: list[str] = field(default_factory=list)


@dataclass
class DecomposedIntent:
    """A single intent from query decomposition (Tier 2)."""

    action: str
    target: str

    def to_query(self) -> str:
        return f"{self.action} {self.target}"


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_EXPAND_PROMPT = """\
Given a user query, extract search keywords and synonyms for tool retrieval.

Query: "{query}"

Output JSON only:
{{"keywords": ["keyword1", "keyword2"], "synonyms": ["syn1", "syn2"],
  "english": ["english_term1", "english_term2"]}}"""

_DECOMPOSE_PROMPT = """\
Break down the user's request into individual tool-level intents.

Query: "{query}"

Output JSON only:
{{"intents": [{{"action": "verb", "target": "noun"}}, ...]}}"""


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response, handling code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class SearchLLM(ABC):
    """Abstract base class for search-enhancing LLM providers."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a response from the LLM."""

    def expand_query(self, query: str) -> ExpandedQuery:
        """Tier 1: Expand query with keywords, synonyms, and English terms."""
        prompt = _EXPAND_PROMPT.format(query=query)
        response = self.generate(prompt)

        try:
            parsed = _extract_json(response)
            return ExpandedQuery(
                keywords=parsed.get("keywords", []),
                synonyms=parsed.get("synonyms", []),
                english_terms=parsed.get("english", []),
            )
        except (json.JSONDecodeError, AttributeError):
            return ExpandedQuery()

    def decompose_intents(self, query: str) -> list[DecomposedIntent]:
        """Tier 2: Decompose query into individual tool-level intents."""
        prompt = _DECOMPOSE_PROMPT.format(query=query)
        response = self.generate(prompt)

        try:
            parsed = _extract_json(response)
            intents = parsed.get("intents", [])
            return [
                DecomposedIntent(action=i.get("action", ""), target=i.get("target", ""))
                for i in intents
                if i.get("action") or i.get("target")
            ]
        except (json.JSONDecodeError, AttributeError):
            return []


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------


class OllamaSearchLLM(SearchLLM):
    """Ollama local model provider for search enhancement."""

    def __init__(
        self,
        model: str = "qwen2.5:1.5b",
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
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
            return result.get("response", "")


# ---------------------------------------------------------------------------
# OpenAI-Compatible Provider
# ---------------------------------------------------------------------------


class OpenAICompatibleSearchLLM(SearchLLM):
    """OpenAI-compatible API provider for search enhancement."""

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
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
