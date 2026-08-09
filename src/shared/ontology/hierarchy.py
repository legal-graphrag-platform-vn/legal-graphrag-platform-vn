"""Canonical structural hierarchy identifiers and bounded query depths."""

from __future__ import annotations

import re
import unicodedata


MAX_DOCUMENT_TO_ARTICLE_DEPTH = 5
MAX_DOCUMENT_TO_RETRIEVAL_UNIT_DEPTH = 6
MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH = 7
MAX_DOCUMENT_HIERARCHY_DEPTH = 7


_VIETNAMESE_ORDINALS = {
    "nhat": "1",
    "mot": "1",
    "hai": "2",
    "ba": "3",
    "tu": "4",
    "nam": "5",
    "sau": "6",
    "bay": "7",
    "tam": "8",
    "chin": "9",
    "muoi": "10",
}


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


def normalize_part_number(value: str) -> str:
    text = value.strip()
    without_prefix = re.sub(r"(?i)^thứ\s+", "", text).strip()
    slug = _slug(without_prefix)
    if slug in _VIETNAMESE_ORDINALS:
        return _VIETNAMESE_ORDINALS[slug]
    return normalize_chapter_number(without_prefix)


def normalize_subsection_number(value: str) -> str:
    return _slug(value.strip().lower())


def legal_number_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Return a deterministic natural-order key for Article/Clause numbers."""
    normalized = _slug(str(value))
    chunks = re.findall(r"\d+|[a-z]+", normalized)
    return tuple((0, int(chunk)) if chunk.isdigit() else (1, chunk) for chunk in chunks)


def part_id(document_id: str, part_number: str) -> str:
    return f"{document_id}_part{normalize_part_number(part_number)}"


def chapter_id(document_id: str, chapter_number: str) -> str:
    return f"{document_id}_ch{normalize_chapter_number(chapter_number)}"


def section_id(document_id: str, chapter_number: str, section_number: str) -> str:
    return (
        f"{chapter_id(document_id, chapter_number)}"
        f"_sec{normalize_section_number(section_number)}"
    )


def subsection_id(
    document_id: str,
    chapter_number: str,
    section_number: str,
    subsection_number: str,
) -> str:
    return (
        f"{section_id(document_id, chapter_number, section_number)}"
        f"_subsec{normalize_subsection_number(subsection_number)}"
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
