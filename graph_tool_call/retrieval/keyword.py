"""BM25 keyword scoring for tool retrieval."""

from __future__ import annotations

import math
import re

from graph_tool_call.core.tool import ToolSchema

# Baseline stopwords — always removed regardless of corpus.
# These are common filler words that never carry discriminative value.
_BASE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "by",
        "is",
        "and",
        "or",
    }
)

# CRUD/action verbs that must never be auto-stopworded — they carry intent.
_PROTECTED_TERMS = frozenset(
    {
        "list",
        "get",
        "read",
        "creat",  # stemmed form of "create"
        "delet",  # stemmed form of "delete"
        "updat",  # stemmed form of "update"
        "patch",
        "put",
        "post",
        "watch",
        "find",
        "search",
        "writ",  # stemmed form of "write"
        "send",
        "add",
        "remov",  # stemmed form of "remove"
        "set",
    }
)

# Suffix-stripping rules applied in order. Each entry: (suffix, min_stem_len).
# min_stem_len prevents over-stemming (e.g. "us" → "u").
_STEM_RULES: list[tuple[str, int]] = [
    ("ies", 2),  # queries → quer, bodies → bodi
    ("ied", 2),  # applied → appl
    ("ing", 3),  # running → runn, listing → list
    ("tion", 3),  # creation → crea, deletion → dele
    ("sion", 3),  # permission → permis
    ("ment", 3),  # deployment → deploy
    ("ness", 3),  # readiness → readi
    ("able", 3),  # readable → read
    ("ible", 3),  # accessible → access
    ("ous", 3),  # dangerous → danger
    ("ive", 3),  # destructive → destruct
    ("ful", 3),  # successful → success
    ("es", 3),  # namespaces → namespac, resources → resourc
    ("ed", 3),  # namespaced → namespac, created → creat
    ("er", 3),  # controller → controll
    ("ly", 3),  # permanently → permanent
    ("s", 3),  # pods → pod, secrets → secret
]


def _stem(token: str) -> str:
    """Lightweight suffix-stripping stemmer for API/tool vocabulary.

    Not a full Porter/Snowball — just enough to normalize plural/tense forms
    that commonly appear in OpenAPI operationIds and tool descriptions.
    """
    if len(token) <= 3:
        return token
    for suffix, min_len in _STEM_RULES:
        if token.endswith(suffix) and len(token) - len(suffix) >= min_len:
            return token[: -len(suffix)]
    return token


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
        stopword_df_threshold: float = 0.7,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._tools = tools
        self._stopword_df_threshold = stopword_df_threshold
        self._doc_freqs: dict[str, int] = {}  # term -> number of docs containing it
        self._doc_lens: dict[str, int] = {}  # tool_name -> doc length
        self._avg_dl: float = 0.0
        self._n_docs: int = 0
        self._tool_tokens: dict[str, list[str]] = {}  # tool_name -> token list
        self._stopwords: frozenset[str] = _BASE_STOPWORDS
        self._build_index()

    def _build_index(self) -> None:
        """Build inverted index from tool corpus."""
        self._n_docs = len(self._tools)
        if self._n_docs == 0:
            return

        total_len = 0
        self._tf_maps: dict[str, dict[str, int]] = {}  # pre-computed tf per doc
        self._name_token_counts: dict[str, int] = {}  # operationId token count
        for name, tool in self._tools.items():
            tokens = self._tokenize_tool(tool)
            self._tool_tokens[name] = tokens
            self._doc_lens[name] = len(tokens)
            total_len += len(tokens)

            # Pre-compute term frequency map
            tf_map: dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            self._tf_maps[name] = tf_map

            # Count name tokens for length penalty
            self._name_token_counts[name] = len(self._tokenize(name))

            # Count document frequency (unique terms per document)
            for term in tf_map:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        self._avg_dl = total_len / self._n_docs if self._n_docs > 0 else 0.0

        # Auto-compute stopwords: tokens appearing in >threshold% of documents
        # but never remove CRUD/action verbs — they carry retrieval intent.
        if self._n_docs >= 10:
            auto_stops = {
                term
                for term, df in self._doc_freqs.items()
                if df / self._n_docs >= self._stopword_df_threshold
                and len(term) <= 4
                and term not in _PROTECTED_TERMS
            }
            self._stopwords = _BASE_STOPWORDS | frozenset(auto_stops)

    def score(self, query: str) -> dict[str, float]:
        """Score all tools against query using BM25.

        Returns dict of tool_name -> BM25 score (only non-zero scores).
        """
        raw_tokens = self._tokenize(query)
        if not raw_tokens:
            return {}
        # Remove stopwords from query; keep all if everything is a stopword
        filtered = [t for t in raw_tokens if t not in self._stopwords]
        query_tokens = filtered if filtered else raw_tokens
        # Expand with scope/action signals from the original query
        query_tokens = self._expand_query_tokens(query_tokens, query)

        scores: dict[str, float] = {}
        for name in self._tool_tokens:
            doc_len = self._doc_lens[name]
            tf_map = self._tf_maps[name]
            doc_score = 0.0

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
                # Penalize long operationIds (noisy partial matches)
                name_len = self._name_token_counts.get(name, 0)
                if name_len > 6:
                    doc_score *= 1.0 / (1.0 + 0.15 * (name_len - 6))

                # Boost when query tokens appear as ordered subsequence in name
                doc_score *= self._name_subsequence_boost(query_tokens, name)

                scores[name] = doc_score

        return scores

    def _name_subsequence_boost(self, query_tokens: list[str], tool_name: str) -> float:
        """Boost score when query tokens match tool name in order."""
        name_tokens = self._tokenize(tool_name)
        if not name_tokens or not query_tokens:
            return 1.0
        qi = 0
        for nt in name_tokens:
            if qi < len(query_tokens) and nt == query_tokens[qi]:
                qi += 1
        match_ratio = qi / len(query_tokens)
        return 1.0 + match_ratio * 0.5  # up to 1.5x boost

    @staticmethod
    def _tokenize_tool(tool: ToolSchema) -> list[str]:
        """Extract tokens from all tool fields: name, description, tags, param names, metadata."""
        tokens: list[str] = []
        tokens.extend(BM25Scorer._tokenize(tool.name))
        tokens.extend(BM25Scorer._tokenize(tool.description))
        for tag in tool.tags:
            tokens.extend(BM25Scorer._tokenize(tag))
        for param in tool.parameters:
            tokens.extend(BM25Scorer._tokenize(param.name))
        tokens.extend(BM25Scorer._extract_metadata_tokens(tool))
        # Include LLM-generated example queries for richer keyword matching
        if hasattr(tool, "metadata") and tool.metadata:
            for eq in tool.metadata.get("example_queries", []):
                tokens.extend(BM25Scorer._tokenize(eq))
        return tokens

    @staticmethod
    def _extract_metadata_tokens(tool: ToolSchema) -> list[str]:
        """Extract discriminative tokens from tool metadata (path, method).

        For OpenAPI tools, the path carries critical scope/sub-resource information
        that descriptions often omit (e.g. namespaced vs cluster-wide).
        """
        metadata = tool.metadata
        if not metadata:
            return []
        tokens: list[str] = []

        method = metadata.get("method", "")
        path = metadata.get("path", "")

        if method:
            tokens.append(method.lower())

        if not path:
            return tokens

        # Split path into segments, skip empty and {param} placeholders
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        for seg in segments:
            tokens.extend(BM25Scorer._tokenize(seg))

        # Scope detection: does the path contain a {namespace} parameter?
        has_namespace_param = "{namespace}" in path or "{ns}" in path
        # Is it a "list" or "get" style path? (ends with plural or has {name})
        has_name_param = "{name}" in path

        if has_namespace_param:
            tokens.extend(["namespac", "scoped"])
        elif any(s in path for s in ["/namespaces", "/namespace"]):
            # Path references namespaces without a param = cluster-level namespace listing
            pass
        else:
            # No namespace scoping at all
            if method.lower() in ("get", "list") or not has_name_param:
                tokens.extend(["cluster", "all"])

        # Sub-resource tokens from path suffix
        if segments:
            last = segments[-1].lower()
            sub_resources = {
                "exec": ["exec", "execut"],
                "attach": ["attach"],
                "portforward": ["portforward", "port", "forward"],
                "proxy": ["proxy"],
                "log": ["log"],
                "status": ["status"],
                "scale": ["scale"],
                "finalize": ["finaliz"],
                "binding": ["bind"],
                "eviction": ["evict"],
                "ephemeralcontainers": ["ephemer", "container"],
            }
            if last in sub_resources:
                tokens.extend(sub_resources[last])

        # Collection pattern: DELETE on a plural path without {name}
        if method.lower() == "delete" and not has_name_param:
            tokens.extend(["collect", "bulk"])

        return tokens

    @staticmethod
    def _expand_query_tokens(tokens: list[str], query: str) -> list[str]:
        """Expand query tokens with scope/action signals detected from the full query.

        Detects multi-word patterns that individual tokens can't capture,
        then adds synthetic tokens that match metadata-derived document tokens.
        """
        q = query.lower()
        extra: list[str] = []

        # Scope detection
        if re.search(r"\bin\s+(a|the|this|default|my)\s+namespace\b", q):
            extra.extend(["namespac", "scoped"])
        elif re.search(r"\ball\s+namespace", q) or "cluster-wide" in q or "across all" in q:
            extra.extend(["cluster", "all"])

        # Sub-resource patterns
        if "port-forward" in q or "port forward" in q or "portforward" in q:
            extra.extend(["portforward", "port", "forward"])
        if re.search(r"\b(exec|execute)\b", q):
            extra.append("exec")
        if re.search(r"\battach\b", q):
            extra.append("attach")

        # Collection/bulk delete
        if re.search(r"\bdelete\s+all\b", q) or re.search(r"\bremove\s+all\b", q) or "at once" in q:
            extra.extend(["collect", "bulk"])

        # Status/logs
        if re.search(r"\bstatus\b", q):
            extra.append("status")
        if re.search(r"\blogs?\b", q):
            extra.append("log")
        if re.search(r"\bscale\b", q):
            extra.append("scale")
        if re.search(r"\bephemeral\b", q):
            extra.append("ephemer")
        if re.search(r"\bproxy\b", q):
            extra.append("proxy")

        if extra:
            return tokens + extra
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
        """Tokenizer with camelCase splitting, stemming, and Korean bigrams.

        Emits both the original lowered token and its stemmed form (if different)
        so that "pods" matches "pod" and "namespaced" matches "namespace".

        Examples:
            "getUserById" -> ["get", "user", "by", "id"]
            "list_all_pets" -> ["list", "all", "pet", "pets"]
            "namespaced" -> ["namespac", "namespaced"]
            "정기주문해지" -> ["정기주문해지", "정기", "기주", "주문", "문해", "해지"]
        """
        # Step 1: Split on separators (underscore, hyphen, space, punctuation)
        parts = re.split(r"[\s_\-/.,;:!?()]+", text)

        tokens: list[str] = []
        for part in parts:
            if not part:
                continue
            # Step 2: Further split camelCase
            camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            camel_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel_split)
            sub_parts = camel_split.split()
            # Step 3: Lowercase, stem, and add Korean bigrams
            for sp in sub_parts:
                lowered = sp.lower()
                if not lowered:
                    continue
                stemmed = _stem(lowered)
                tokens.append(stemmed)
                if stemmed != lowered:
                    tokens.append(lowered)
                # Add Korean bigrams if the token contains Korean characters
                if re.search(r"[\uac00-\ud7af]", lowered):
                    bigrams = BM25Scorer._korean_bigrams(lowered)
                    tokens.extend(bigrams)

        return tokens
