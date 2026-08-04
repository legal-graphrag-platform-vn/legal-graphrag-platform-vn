"""Deterministic clarification questions and reply matching (Plan 19 §4).

Questions are generated from candidate labels without calling any model.
"""

from __future__ import annotations

import re

from persistence.domain import ClarificationCandidate, PendingClarification
from resolution.models import ExpectedUnitType

_CANCEL_PHRASES = frozenset({"hủy", "huỷ", "bỏ qua", "hủy bỏ", "huỷ bỏ", "thôi"})

_UNIT_NOUN = {
    ExpectedUnitType.DOCUMENT: "văn bản",
    ExpectedUnitType.ARTICLE: "điều",
    ExpectedUnitType.CLAUSE: "khoản",
    ExpectedUnitType.POINT: "điểm",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" \t\r\n!?.,")


def is_cancel(message: str) -> bool:
    return _normalize(message) in _CANCEL_PHRASES


def build_select_question(candidates: tuple[ClarificationCandidate, ...]) -> str:
    lines = [
        f"{index}. {candidate.label}"
        for index, candidate in enumerate(candidates, start=1)
    ]
    listing = " ".join(lines)
    return (
        "Ý bạn là văn bản nào? " + listing + " Vui lòng trả lời bằng số thứ tự "
        "hoặc tên, hoặc gõ 'hủy' để bỏ qua."
    )


def build_restate_question(expected_type: ExpectedUnitType | None) -> str:
    noun = _UNIT_NOUN.get(expected_type, "nội dung") if expected_type else "nội dung"
    return (
        f"Tôi chưa xác định được {noun} bạn đang nhắc đến. "
        "Bạn vui lòng nêu rõ hơn hoặc đặt lại câu hỏi đầy đủ."
    )


def match_select(
    pending: PendingClarification, message: str
) -> ClarificationCandidate | None:
    """Resolve a SELECT reply by ordinal or normalized label (Plan 19 §4)."""
    normalized = _normalize(message)
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(pending.candidates):
            return pending.candidates[index - 1]
        return None
    for candidate in pending.candidates:
        if _normalize(candidate.label) == normalized:
            return candidate
    return None
