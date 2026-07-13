"""Citation labels and stable application deep links for retrieved legal units."""

from urllib.parse import quote


def build_citation_label(
    *,
    label: str,
    document_number: str | None,
    article_number: str | None,
    clause_number: str | None,
) -> str:
    parts: list[str] = []
    if article_number:
        parts.append(f"Điều {article_number}")
    if label == "Clause" and clause_number:
        parts.append(f"Khoản {clause_number}")
    if not parts:
        parts.append(label)
    if document_number:
        parts.append(document_number)
    return ", ".join(parts)


def build_deep_link(document_id: str, unit_id: str) -> str:
    """Return an internal link independent of corpus folder names and ID prefixes."""

    return f"/documents/{quote(document_id, safe='')}/units/{quote(unit_id, safe='')}"
