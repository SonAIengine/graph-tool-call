"""Optional pluggable tokenizers for BM25 keyword scoring.

Lets callers inject a custom tokenizer (e.g. a Korean morphological analyzer) so
that Korean queries split into clean content morphemes instead of character
bigrams. The library stays zero-dependency: ``kiwipiepy`` is an optional extra,
imported lazily so that a missing install never breaks ``import graph_tool_call``.

Mirrors the ``wrap_embedding`` / ``wrap_llm`` auto-detection pattern.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable

from graph_tool_call.retrieval.keyword import BM25Scorer, _stem

Tokenizer = Callable[[str], list[str]]

# Reuse the built-in tokenizer's separator + camelCase splitting so English /
# operationId tokens are byte-for-byte identical to the default path.
_SPLIT = re.compile(r"[\s_\-/.,;:!?()]+")
_HANGUL = re.compile(r"[가-힯]")

# Kiwi POS tags that carry retrieval meaning. Drops josa (JK*), eomi (E*),
# punctuation (S[FPS]) and other function morphemes that pollute the index.
_KEEP_POS = frozenset(
    {
        "NNG",  # common noun
        "NNP",  # proper noun
        "NNB",  # dependent noun
        "VV",  # verb stem
        "VA",  # adjective stem
        "XR",  # root
        "SL",  # foreign (latin) word
        "SH",  # hanja
        "SN",  # number
    }
)


class KiwiTokenizer:
    """Hybrid tokenizer: English pipeline preserved, Korean spans → Kiwi morphemes.

    Non-Korean sub-tokens go through the same lowercase + stem path as the
    built-in :meth:`BM25Scorer._tokenize` (so English / operationId quality is
    unchanged). Korean sub-tokens are split into content morphemes; if Kiwi
    returns nothing usable (OOV / compound it cannot split), we fall back to
    character bigrams for recall safety.
    """

    def __init__(self) -> None:
        try:
            from kiwipiepy import Kiwi
        except ImportError as exc:  # pragma: no cover - only without the extra
            msg = (
                "kiwipiepy is required for the 'kiwi' tokenizer. "
                "Install with: pip install graph-tool-call[korean]"
            )
            raise ImportError(msg) from exc
        self._kiwi = Kiwi()
        # kiwipiepy analysis is not guaranteed reentrant across threads; the
        # retrieval engine may call tokenization from an executor pool.
        self._lock = threading.Lock()

    def _morphs(self, span: str) -> list[str]:
        with self._lock:
            tokens = self._kiwi.tokenize(span)
        return [t.form.lower() for t in tokens if t.tag in _KEEP_POS]

    def __call__(self, text: str) -> list[str]:
        out: list[str] = []
        for part in _SPLIT.split(text):
            if not part:
                continue
            camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
            camel = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel)
            for sp in camel.split():
                lowered = sp.lower()
                if not lowered:
                    continue
                if _HANGUL.search(lowered):
                    morphs = self._morphs(lowered)
                    out.extend(morphs if morphs else BM25Scorer._korean_bigrams(lowered))
                else:
                    stemmed = _stem(lowered)
                    out.append(stemmed)
                    if stemmed != lowered:
                        out.append(lowered)
        return out


def wrap_tokenizer(tokenizer: object) -> Tokenizer | None:
    """Normalize a tokenizer spec into a callable (or ``None`` for the default).

    Accepts:
      - ``None`` → ``None`` (use the built-in ``BM25Scorer._tokenize``)
      - a callable ``str -> list[str]`` → returned as-is (trusted pass-through;
        a :class:`KiwiTokenizer` instance also matches here)
      - the string ``"kiwi"`` → builds a :class:`KiwiTokenizer` (needs the
        ``[korean]`` extra)

    Raises ``TypeError`` on anything else.
    """
    if tokenizer is None:
        return None
    if callable(tokenizer):
        return tokenizer
    if isinstance(tokenizer, str):
        key = tokenizer.strip().lower()
        if key == "kiwi" or key.startswith("kiwi/"):
            return KiwiTokenizer()
        msg = f"Unknown tokenizer spec: {tokenizer!r}. Pass 'kiwi', a callable, or None."
        raise TypeError(msg)
    got = type(tokenizer).__name__
    msg = f"tokenizer must be 'kiwi', a callable str->list[str], or None, got {got}"
    raise TypeError(msg)
