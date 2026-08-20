"""Citation labels and stable application deep links for retrieved legal units."""

from urllib.parse import quote


def build_citation_label(
    *,
    label: str,
    document_number: str | None,
    article_number: str | None,
    clause_number: str | None,
    appendix_number: str | None = None,
) -> str:
    parts: list[str] = []
    if label == "Appendix":
        parts.append(f"Phụ lục {appendix_number}" if appendix_number else "Phụ lục")
    elif article_number:
        parts.append(f"Điều {article_number}")
    if label == "Clause" and clause_number:
        parts.append(f"Khoản {clause_number}")
    if label != "Appendix" and appendix_number:
        # This unit is scoped by an Appendix ID (an Article/Clause/Point that
        # lives inside an Appendix rather than the host Document's own body).
        # Disambiguate it in the citation text: legal_ontology.md explicitly
        # allows an Article 1 inside an Appendix to share its number with an
        # unrelated Article 1 in the host Document — IDs never collide, but
        # without this the citation label would read identically for both.
        parts.append(f"Phụ lục {appendix_number}")
    if not parts:
        parts.append(label)
    if document_number:
        parts.append(document_number)
    return ", ".join(parts)


def build_deep_link(document_id: str, unit_id: str) -> str:
    """Return an internal link independent of corpus folder names and ID prefixes."""

    return f"/documents/{quote(document_id, safe='')}/units/{quote(unit_id, safe='')}"
