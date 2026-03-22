"""Zero-LLM intent classifier for query → behavioral intent mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Korean postpositions (조사) to strip from tokens
_KOREAN_POSTPOSITIONS = re.compile(
    r"(을|를|이|가|은|는|에|에서|에게|께|로|으로|와|과|의|도|만|까지|부터|라도|처럼)$"
)

# Korean verb endings to strip for stem extraction
_KOREAN_VERB_ENDINGS = re.compile(
    r"(해줘|해주세요|해주실래요|해줄래|해주기|하기|합니다|해요|해봐|하고|해야|하는|해라|하자)$"
)

# Keyword dictionaries for intent classification (Korean + English)
_READ_KEYWORDS = frozenset(
    {
        "get",
        "list",
        "show",
        "read",
        "fetch",
        "retrieve",
        "search",
        "find",
        "view",
        "query",
        "lookup",
        "check",
        "inspect",
        "describe",
        "display",
        "browse",
        "조회",
        "목록",
        "보기",
        "보여",
        "검색",
        "확인",
        "열람",
        "표시",
        "가져오기",
        "가져와",
        "찾기",
        "찾아",
        "얻기",
        "얻어",
        "살펴",
        "알려",
    }
)

_WRITE_KEYWORDS = frozenset(
    {
        "create",
        "add",
        "update",
        "modify",
        "edit",
        "set",
        "put",
        "post",
        "write",
        "change",
        "patch",
        "configure",
        "save",
        "upload",
        "submit",
        "register",
        "process",
        "execute",
        "run",
        "perform",
        "request",
        "apply",
        "enable",
        "activate",
        "trigger",
        "send",
        "invite",
        "assign",
        "merge",
        "approve",
        "publish",
        "deploy",
        "생성",
        "추가",
        "수정",
        "변경",
        "편집",
        "설정",
        "등록",
        "저장",
        "업로드",
        "작성",
        "만들어",
        "바꿔",
        "고쳐",
        "넣어",
    }
)

_DELETE_KEYWORDS = frozenset(
    {
        "delete",
        "remove",
        "destroy",
        "drop",
        "purge",
        "erase",
        "unregister",
        "revoke",
        "cancel",
        "terminate",
        "disable",
        "삭제",
        "제거",
        "취소",
        "해제",
        "폐기",
        "비활성화",
        "해지",
        "지워",
        "없애",
    }
)


@dataclass
class QueryIntent:
    """Behavioral intent extracted from a query.

    Each dimension is a float in [0.0, 1.0] representing confidence.
    """

    read_intent: float = 0.0
    write_intent: float = 0.0
    delete_intent: float = 0.0

    @property
    def is_neutral(self) -> bool:
        """True if no strong intent signal detected."""
        return self.read_intent == 0.0 and self.write_intent == 0.0 and self.delete_intent == 0.0


def _normalize_korean(text: str) -> str:
    """Normalize Korean text by stripping postpositions and verb endings.

    Examples:
        "사용자를 삭제해줘" → "사용자 삭제"
        "목록을 조회해주세요" → "목록 조회"
    """
    tokens = text.split()
    normalized = []
    for token in tokens:
        # Strip verb endings first (longer patterns)
        t = _KOREAN_VERB_ENDINGS.sub("", token)
        # Then strip postpositions
        t = _KOREAN_POSTPOSITIONS.sub("", t)
        if t:
            normalized.append(t)
    return " ".join(normalized)


def classify_intent(query: str) -> QueryIntent:
    """Classify query into behavioral intent using keyword matching.

    Supports Korean and English keywords with Korean morpheme normalization.
    Returns neutral intent if no keywords match.
    """
    # Normalize Korean: strip postpositions and verb endings
    normalized = _normalize_korean(query)
    tokens = set(normalized.lower().split())
    # Also check original tokens (for keywords that include endings like "보여")
    tokens |= set(query.lower().split())

    read_hits = len(tokens & _READ_KEYWORDS)
    write_hits = len(tokens & _WRITE_KEYWORDS)
    delete_hits = len(tokens & _DELETE_KEYWORDS)

    total = read_hits + write_hits + delete_hits
    if total == 0:
        return QueryIntent()

    return QueryIntent(
        read_intent=min(read_hits / total, 1.0),
        write_intent=min(write_hits / total, 1.0),
        delete_intent=min(delete_hits / total, 1.0),
    )
