"""Shared matching helpers for OpenAPI IO contract rows."""

from __future__ import annotations

import re
from typing import Any

IDENTIFIER_SUFFIXES = ("id", "ids", "no", "nos", "num", "number", "code", "key", "seq", "uuid")

_GENERIC_DESCRIPTION_ALIAS_KEYS = frozenset(
    {
        "id",
        "identifier",
        "no",
        "number",
        "code",
        "key",
        "seq",
        "sequence",
        "uuid",
        "name",
        "title",
        "status",
        "state",
        "type",
        "value",
        "flag",
        "description",
        "content",
        "아이디",
        "식별자",
        "번호",
        "코드",
        "키",
        "순번",
        "일련번호",
        "명",
        "이름",
        "제목",
        "상태",
        "유형",
        "타입",
        "값",
        "여부",
        "구분",
        "내용",
        "설명",
        "목록",
        "리스트",
        "일자",
        "날짜",
    }
)


def canonical_field_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def canonical_description_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").strip().lower())


def split_field_words(field_name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(field_name or ""))
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [token.lower() for token in re.split(r"[^A-Za-z0-9]+", spaced) if token]


def is_identifier_like(field_name: str) -> bool:
    words = split_field_words(field_name)
    if not words:
        return False
    if len(words) == 1 and words[0] in {"id", "no", "key", "code", "seq"}:
        return False
    return words[-1] in IDENTIFIER_SUFFIXES


def description_alias_key(row: dict[str, Any] | None) -> str:
    """Return a conservative alias key for identifier rows with useful descriptions.

    OpenAPI generators often expose the same business identifier with different
    field names in nearby DTOs, for example ``marketingDisplayNo`` and
    ``mkdpNo``. When both rows share a specific description such as
    ``기획전번호``, that description is useful evidence for data-flow matching.
    Broad labels such as ``번호`` or ``code`` are intentionally ignored.
    """

    if not isinstance(row, dict):
        return ""
    field_name = str(row.get("field_name") or "").strip()
    if not is_identifier_like(field_name):
        return ""
    key = canonical_description_key(row.get("description"))
    if not key or key in _GENERIC_DESCRIPTION_ALIAS_KEYS:
        return ""
    if len(key) < 3:
        return ""
    return key
