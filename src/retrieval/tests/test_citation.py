from __future__ import annotations

from src.retrieval.citation import build_citation_label, build_deep_link


def test_article_citation_label() -> None:
    label = build_citation_label(
        label="Article",
        document_number="59/2020/QH14",
        article_number="17",
        clause_number=None,
    )
    assert label == "Điều 17, 59/2020/QH14"


def test_clause_citation_label() -> None:
    label = build_citation_label(
        label="Clause",
        document_number="59/2020/QH14",
        article_number="17",
        clause_number="1",
    )
    assert label == "Điều 17, Khoản 1, 59/2020/QH14"


def test_appendix_citation_label() -> None:
    label = build_citation_label(
        label="Appendix",
        document_number="38/2014/TT-BTC",
        article_number=None,
        clause_number=None,
        appendix_number="01/TDG",
    )
    assert label == "Phụ lục 01/TDG, 38/2014/TT-BTC"


def test_appendix_without_number_falls_back_to_generic_label() -> None:
    label = build_citation_label(
        label="Appendix",
        document_number="38/2014/TT-BTC",
        article_number=None,
        clause_number=None,
        appendix_number=None,
    )
    assert label == "Phụ lục, 38/2014/TT-BTC"


def test_article_scoped_by_appendix_is_disambiguated_in_the_label() -> None:
    """An Article living inside an Appendix can legitimately share its number
    with an unrelated Article in the host Document's own body (their IDs are
    scoped by the Appendix ID and never collide) — the citation text must
    still tell them apart, or a user reading two "Điều 1" citations can't
    tell which document body they actually come from."""
    label = build_citation_label(
        label="Article",
        document_number="38/2014/TT-BTC",
        article_number="1",
        clause_number=None,
        appendix_number="01/TDG",
    )
    assert label == "Điều 1, Phụ lục 01/TDG, 38/2014/TT-BTC"


def test_clause_scoped_by_appendix_is_disambiguated_in_the_label() -> None:
    label = build_citation_label(
        label="Clause",
        document_number="38/2014/TT-BTC",
        article_number="1",
        clause_number="2",
        appendix_number="01/TDG",
    )
    assert label == "Điều 1, Khoản 2, Phụ lục 01/TDG, 38/2014/TT-BTC"


def test_deep_link_is_scoped_to_document_and_unit() -> None:
    assert (
        build_deep_link("ldn_2020", "ldn_2020_art17")
        == "/documents/ldn_2020/units/ldn_2020_art17"
    )


def test_deep_link_escapes_unsafe_characters() -> None:
    assert (
        build_deep_link("doc a/b", "unit c/d")
        == "/documents/doc%20a%2Fb/units/unit%20c%2Fd"
    )
