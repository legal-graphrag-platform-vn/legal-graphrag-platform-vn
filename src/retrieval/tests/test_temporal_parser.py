from src.retrieval.query.temporal_parser import TemporalParser


def test_temporal_parser_does_not_treat_after_tax_as_time_expression() -> None:
    parsed = TemporalParser().parse(
        "Doanh nghiệp xã hội sử dụng bao nhiêu phần trăm lợi nhuận sau thuế?"
    )

    assert parsed.has_temporal is False
    assert parsed.parse_error is None


def test_temporal_parser_flags_relative_amendment_comparison() -> None:
    parsed = TemporalParser().parse(
        "So sánh quy định trước và sau khi sửa đổi luật doanh nghiệp"
    )

    assert parsed.has_temporal is False
    assert parsed.spans_all_versions is True
    assert parsed.resolved_from is None
    assert parsed.resolved_to is None


def test_temporal_parser_flags_relative_repeal_comparison() -> None:
    parsed = TemporalParser().parse(
        "Quy định trước khi bãi bỏ khác gì so với hiện tại?"
    )

    assert parsed.spans_all_versions is True


def test_temporal_parser_does_not_flag_ordinary_amendment_wording() -> None:
    """Only the relative before/after comparison phrasing should set
    spans_all_versions — a plain VALIDITY-style question about an amendment
    must not be silently treated as a version-spanning comparison."""
    parsed = TemporalParser().parse("Điều 5 đã bị sửa đổi bởi văn bản nào?")

    assert parsed.spans_all_versions is False


def test_current_validity_takes_precedence_over_document_edition_year() -> None:
    parsed = TemporalParser().parse(
        "Luật Doanh nghiệp năm 2014 hiện nay còn hiệu lực không?"
    )

    assert parsed.requests_current_validity is True
    assert parsed.expression == "hiện nay"
    assert parsed.resolved_from is None
    assert parsed.resolved_to is None
