"""Zero-LLM intent classifier for query → behavioral intent mapping."""

from __future__ import annotations

from dataclasses import dataclass

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
        "검색",
        "확인",
        "열람",
        "표시",
        "가져오기",
        "찾기",
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


def classify_intent(query: str) -> QueryIntent:
    """Classify query into behavioral intent using keyword matching.

    Supports Korean and English keywords. Returns neutral intent if
    no keywords match.
    """
    tokens = set(query.lower().split())

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
