"""Canonical structural hierarchy identifiers and bounded query depths."""

from __future__ import annotations

import re
import unicodedata


MAX_DOCUMENT_TO_ARTICLE_DEPTH = 3
MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH = 4
MAX_DOCUMENT_HIERARCHY_DEPTH = 5


def normalize_chapter_number(value: str) -> str:
    text = value.strip().upper()
    roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    if re.fullmatch(r"[IVXLCDM]+", text):
        total = 0
        previous = 0
        for character in reversed(text):
            current = roman_values[character]
            if current < previous:
                total -= current
            else:
                total += current
                previous = current
        return str(total)
    return _slug(value)


def normalize_section_number(value: str) -> str:
    return _slug(value.strip().lower())


def chapter_id(document_id: str, chapter_number: str) -> str:
    return f"{document_id}_ch{normalize_chapter_number(chapter_number)}"


def section_id(document_id: str, chapter_number: str, section_number: str) -> str:
    return (
        f"{chapter_id(document_id, chapter_number)}"
        f"_sec{normalize_section_number(section_number)}"
    )


def _slug(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    ascii_text = without_marks.replace("đ", "d").replace("Đ", "D").lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    if not normalized:
        raise ValueError("Structural number must contain at least one letter or digit")
    return normalized
