"""Deterministic parser for explicit Vietnamese legal references (Plan 19 §4).

Recognises document numbers, law name/year, and Điều/Khoản/Điểm. It never infers
canonical identity — it only extracts structural components for the read-only
lookup to confirm.
"""

from __future__ import annotations

import re

from resolution.models import ExplicitReference

# 59/2020/QH14, 01/2021/NĐ-CP, ...
_DOCUMENT_NUMBER = re.compile(r"\d{1,5}/\d{4}/[0-9A-Za-zĐđ]+(?:-[0-9A-Za-zĐđ]+)*")
# "Luật Doanh nghiệp 2020", "Bộ luật Lao động 2019"
_LAW_NAME = re.compile(
    r"((?:Bộ\s+luật|Luật)\s+[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]*?)\s+(?:năm\s+)?(\d{4})",
    re.IGNORECASE,
)
_LAW_NAME_WITHOUT_YEAR = re.compile(
    r"((?:Bộ\s+luật|Luật)\s+[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s]*?)"
    r"(?=\s+(?:có|quy\s+định|dẫn\s+chiếu|nói|được|đang|hiện|áp\s+dụng|thì)\b"
    r"|\s+và\s+(?:Bộ\s+luật|Luật)\b|[?,.;:]|$)",
    re.IGNORECASE,
)
_LAW_ANAPHORA = frozenset({"luật này", "luật đó", "luật trên"})
_ARTICLE = re.compile(r"Điều\s+(\d+[A-Za-zĐđ]?)", re.IGNORECASE)
_CLAUSE = re.compile(r"Khoản\s+(\d+)", re.IGNORECASE)
_POINT = re.compile(r"Điểm\s+([A-Za-zĐđ])\b", re.IGNORECASE)

_MAX_REFERENCES = 5


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def parse_explicit_references(message: str) -> list[ExplicitReference]:
    """Return the distinct explicit references mentioned in the message.

    An empty list means the message has no explicit structural reference.
    """
    document_numbers = _unique(_DOCUMENT_NUMBER.findall(message))
    law_refs = [(name.strip(), int(year)) for name, year in _LAW_NAME.findall(message)]
    named_without_year = [
        (name.strip(), None)
        for name in _LAW_NAME_WITHOUT_YEAR.findall(message)
        if name.strip().casefold() not in _LAW_ANAPHORA
    ]
    law_refs = list(dict.fromkeys([*law_refs, *named_without_year]))
    articles = _unique(_ARTICLE.findall(message))
    clauses = _unique(_CLAUSE.findall(message))
    points = _unique([label.lower() for label in _POINT.findall(message)])

    # Document identities: explicit numbers first, then named laws.
    identities: list[tuple[str | None, str | None, int | None]] = []
    for number in document_numbers:
        identities.append((number, None, None))
    for name, year in law_refs:
        identities.append((None, name, year))
    if not identities:
        identities.append((None, None, None))

    # A single structural chain attaches to every identity; multiple articles
    # expand into separate references so the lookup can surface ambiguity.
    single_clause = clauses[0] if len(clauses) == 1 else None
    single_point = points[0] if len(points) == 1 else None
    article_options: list[str | None] = list(articles) if articles else [None]

    references: list[ExplicitReference] = []
    for document_number, law_name, law_year in identities:
        for article in article_options:
            reference = ExplicitReference(
                document_number=document_number,
                law_name=law_name,
                law_year=law_year,
                article_number=article,
                clause_number=single_clause if article else None,
                point_label=single_point if article else None,
            )
            if reference.is_present:
                references.append(reference)
            if len(references) >= _MAX_REFERENCES:
                return references
    return references
