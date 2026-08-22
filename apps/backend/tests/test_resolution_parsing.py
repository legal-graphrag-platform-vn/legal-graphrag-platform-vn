"""Unit tests for the explicit parser and anaphora detector (Plan 19 §4)."""

from __future__ import annotations

from resolution.anaphora import detect_anaphora
from resolution.explicit_parser import parse_explicit_references
from resolution.models import ExpectedUnitType


# --------------------------------------------------------------------------- #
# Explicit parser                                                              #
# --------------------------------------------------------------------------- #


def test_parses_article_with_named_law_and_year() -> None:
    refs = parse_explicit_references("Điều 111 Luật Doanh nghiệp 2020 quy định gì")
    assert len(refs) == 1
    ref = refs[0]
    assert ref.article_number == "111"
    assert ref.law_name == "Luật Doanh nghiệp"
    assert ref.law_year == 2020
    assert ref.deepest_unit_type is ExpectedUnitType.ARTICLE


def test_parses_article_with_named_law_without_year_at_sentence_end() -> None:
    refs = parse_explicit_references(
        "Cơ quan nào có thẩm quyền xử lý, có dẫn chiếu từ Điều 16 Luật Doanh nghiệp?"
    )

    assert len(refs) == 1
    assert refs[0].article_number == "16"
    assert refs[0].law_name == "Luật Doanh nghiệp"
    assert refs[0].law_year is None


def test_named_law_without_year_stops_before_question_predicate() -> None:
    refs = parse_explicit_references("Điều 3 Luật Đất đai quy định gì?")

    assert len(refs) == 1
    assert refs[0].article_number == "3"
    assert refs[0].law_name == "Luật Đất đai"


def test_generic_law_anaphora_is_not_parsed_as_a_named_law() -> None:
    refs = parse_explicit_references("Điều 17 Luật này quy định gì?")

    assert len(refs) == 1
    assert refs[0].article_number == "17"
    assert refs[0].law_name is None


def test_parses_document_number() -> None:
    refs = parse_explicit_references("Theo 59/2020/QH14 Điều 5")
    assert refs[0].document_number == "59/2020/QH14"
    assert refs[0].article_number == "5"


def test_parses_full_point_clause_article_chain() -> None:
    ref = parse_explicit_references("Điểm a Khoản 2 Điều 3")[0]
    assert ref.article_number == "3"
    assert ref.clause_number == "2"
    assert ref.point_label == "a"
    assert ref.deepest_unit_type is ExpectedUnitType.POINT


def test_standalone_message_has_no_explicit_reference() -> None:
    assert parse_explicit_references("công ty cổ phần là gì") == []


def test_dieu_kien_is_not_an_article_reference() -> None:
    assert parse_explicit_references("điều kiện thành lập doanh nghiệp") == []


def test_multiple_articles_expand_into_separate_references() -> None:
    refs = parse_explicit_references("So sánh Điều 111 và Điều 112")
    assert {ref.article_number for ref in refs} == {"111", "112"}


def test_reference_count_is_bounded() -> None:
    message = " ".join(f"Điều {n}" for n in range(1, 12))
    assert len(parse_explicit_references(message)) <= 5


# --------------------------------------------------------------------------- #
# Anaphora detector                                                            #
# --------------------------------------------------------------------------- #


def test_clause_anaphora_expects_clause() -> None:
    result = detect_anaphora("khoản đó quy định gì")
    assert result is not None
    assert result.expected_type is ExpectedUnitType.CLAUSE


def test_article_anaphora_expects_article() -> None:
    assert detect_anaphora("điều này").expected_type is ExpectedUnitType.ARTICLE


def test_document_anaphora_expects_document() -> None:
    assert detect_anaphora("văn bản trên").expected_type is ExpectedUnitType.DOCUMENT


def test_generic_reference_has_no_expected_type() -> None:
    assert detect_anaphora("quy định vừa nêu").expected_type is None
    assert detect_anaphora("nó áp dụng khi nào").expected_type is None


def test_point_is_more_specific_than_article() -> None:
    assert detect_anaphora("điểm đó của điều này").expected_type is (
        ExpectedUnitType.POINT
    )


def test_no_anaphora_returns_none() -> None:
    assert detect_anaphora("công ty cổ phần là gì") is None
    assert detect_anaphora("điều kiện này ra sao") is None
