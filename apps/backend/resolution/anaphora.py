"""Deterministic anaphora detection for follow-up references (Plan 19 §4).

Recognises demonstrative references such as "điều này", "khoản đó",
"văn bản trên", "quy định vừa nêu" and the bare pronoun "nó". The expected
legal-unit type filters grounded focuses; a generic referent has no type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from resolution.models import ExpectedUnitType

# Demonstratives that turn a legal-unit noun into a back-reference.
_DEMONSTRATIVE = r"(?:này|đó|trên|ấy|vừa\s+nêu|nêu\s+trên|đã\s+nêu)"

_ARTICLE = re.compile(rf"điều\s+{_DEMONSTRATIVE}", re.IGNORECASE)
_CLAUSE = re.compile(rf"khoản\s+{_DEMONSTRATIVE}", re.IGNORECASE)
_POINT = re.compile(rf"điểm\s+{_DEMONSTRATIVE}", re.IGNORECASE)
_DOCUMENT = re.compile(
    rf"(?:văn\s+bản|bộ\s+luật|luật|nghị\s+định|thông\s+tư)\s+{_DEMONSTRATIVE}",
    re.IGNORECASE,
)
_GENERIC = re.compile(rf"quy\s+định\s+{_DEMONSTRATIVE}", re.IGNORECASE)
_PRONOUN = re.compile(r"(?<![0-9A-Za-zÀ-ỹ])nó(?![0-9A-Za-zÀ-ỹ])", re.IGNORECASE)


@dataclass(frozen=True)
class AnaphoraReference:
    """A detected back-reference and the focus type it expects.

    ``expected_type`` is ``None`` for a type-agnostic referent.
    """

    expected_type: ExpectedUnitType | None


# Most specific first, so replacement targets the tightest referent.
_ORDERED_PATTERNS = (_POINT, _CLAUSE, _ARTICLE, _DOCUMENT, _GENERIC, _PRONOUN)


def detect_anaphora(message: str) -> AnaphoraReference | None:
    """Return the most specific anaphora in the message, or None."""
    if _POINT.search(message):
        return AnaphoraReference(ExpectedUnitType.POINT)
    if _CLAUSE.search(message):
        return AnaphoraReference(ExpectedUnitType.CLAUSE)
    if _ARTICLE.search(message):
        return AnaphoraReference(ExpectedUnitType.ARTICLE)
    if _DOCUMENT.search(message):
        return AnaphoraReference(ExpectedUnitType.DOCUMENT)
    if _GENERIC.search(message) or _PRONOUN.search(message):
        return AnaphoraReference(None)
    return None


def replace_first_anaphora(message: str, replacement: str) -> str | None:
    """Replace the most specific anaphora phrase with ``replacement``.

    Returns None when the message contains no anaphora phrase.
    """
    best: re.Match[str] | None = None
    for pattern in _ORDERED_PATTERNS:
        match = pattern.search(message)
        if match is not None:
            best = match
            break
    if best is None:
        return None
    return message[: best.start()] + replacement + message[best.end() :]
