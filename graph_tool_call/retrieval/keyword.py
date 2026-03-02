"""BM25 keyword scoring for tool retrieval."""

from __future__ import annotations

import math
import re

from graph_tool_call.core.tool import ToolSchema


class BM25Scorer:
    """BM25 scoring for tool corpus.

    Directly implemented (no external library) because:
    - Tool corpus is small (typically <1000 tools)
    - Need tool-specific tokenization (camelCase splitting, etc.)
    """

    def __init__(
        self,
        tools: dict[str, ToolSchema],
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._tools = tools
        self._doc_freqs: dict[str, int] = {}  # term -> number of docs containing it
        self._doc_lens: dict[str, int] = {}  # tool_name -> doc length
        self._avg_dl: float = 0.0
        self._n_docs: int = 0
        self._tool_tokens: dict[str, list[str]] = {}  # tool_name -> token list
        self._build_index()

    def _build_index(self) -> None:
        """Build inverted index from tool corpus."""
        self._n_docs = len(self._tools)
        if self._n_docs == 0:
            return

        total_len = 0
        for name, tool in self._tools.items():
            tokens = self._tokenize_tool(tool)
            self._tool_tokens[name] = tokens
            self._doc_lens[name] = len(tokens)
            total_len += len(tokens)

            # Count document frequency (unique terms per document)
            unique_terms = set(tokens)
            for term in unique_terms:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        self._avg_dl = total_len / self._n_docs if self._n_docs > 0 else 0.0

    def score(self, query: str) -> dict[str, float]:
        """Score all tools against query using BM25.

        Returns dict of tool_name -> BM25 score (only non-zero scores).
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return {}

        scores: dict[str, float] = {}
        for name, doc_tokens in self._tool_tokens.items():
            doc_len = self._doc_lens[name]
            doc_score = 0.0

            # Count term frequencies in this document
            tf_map: dict[str, int] = {}
            for token in doc_tokens:
                tf_map[token] = tf_map.get(token, 0) + 1

            for q_term in query_tokens:
                tf = tf_map.get(q_term, 0)
                if tf == 0:
                    continue

                # IDF: log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
                n_qi = self._doc_freqs.get(q_term, 0)
                idf = math.log((self._n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1.0)

                # BM25 term score
                numerator = tf * (self._k1 + 1.0)
                denominator = tf + self._k1 * (1.0 - self._b + self._b * doc_len / self._avg_dl)
                doc_score += idf * numerator / denominator

            if doc_score > 0:
                scores[name] = doc_score

        return scores

    @staticmethod
    def _tokenize_tool(tool: ToolSchema) -> list[str]:
        """Extract tokens from all tool fields: name, description, tags, param names."""
        tokens: list[str] = []
        tokens.extend(BM25Scorer._tokenize(tool.name))
        tokens.extend(BM25Scorer._tokenize(tool.description))
        for tag in tool.tags:
            tokens.extend(BM25Scorer._tokenize(tag))
        for param in tool.parameters:
            tokens.extend(BM25Scorer._tokenize(param.name))
        return tokens

    @staticmethod
    def _korean_bigrams(text: str) -> list[str]:
        """Generate character-level bigrams from Korean (Hangul) text.

        Only processes characters in the Hangul syllable range (U+AC00–U+D7AF).
        Returns empty list if fewer than 2 Korean characters are found.

        Examples:
            "정기주문해지하기" -> ["정기", "기주", "주문", "문해", "해지", "지하", "하기"]
            "a" -> []
            "한" -> []
        """
        korean_chars = [ch for ch in text if "\uac00" <= ch <= "\ud7af"]
        if len(korean_chars) < 2:
            return []
        return [korean_chars[i] + korean_chars[i + 1] for i in range(len(korean_chars) - 1)]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Improved tokenizer: splits camelCase, snake_case, kebab-case, Korean bigrams.

        Examples:
            "getUserById" -> ["get", "user", "by", "id"]
            "list_all_pets" -> ["list", "all", "pets"]
            "send-email" -> ["send", "email"]
            "정기주문해지" -> ["정기주문해지", "정기", "기주", "주문", "문해", "해지"]
        """
        # Step 1: Split on separators (underscore, hyphen, space, punctuation)
        parts = re.split(r"[\s_\-/.,;:!?()]+", text)

        tokens: list[str] = []
        for part in parts:
            if not part:
                continue
            # Step 2: Further split camelCase
            # Insert boundary before uppercase letters that follow lowercase letters
            # e.g. "getUserById" -> "get User By Id"
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            # Also split sequences of uppercase followed by lowercase
            # e.g. "HTMLParser" -> "HTML Parser"
            camel_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
            sub_parts = camel_split.split()
            # Step 3: Lowercase all and add Korean bigrams
            for sp in sub_parts:
                lowered = sp.lower()
                if lowered:
                    tokens.append(lowered)
                    # Add Korean bigrams if the token contains Korean characters
                    if re.search(r"[\uac00-\ud7af]", lowered):
                        bigrams = BM25Scorer._korean_bigrams(lowered)
                        tokens.extend(bigrams)

        return tokens
