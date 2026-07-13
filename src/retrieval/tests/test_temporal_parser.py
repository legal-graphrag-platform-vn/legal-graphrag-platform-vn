from src.retrieval.query.temporal_parser import TemporalParser


def test_temporal_parser_does_not_treat_after_tax_as_time_expression() -> None:
    parsed = TemporalParser().parse(
        "Doanh nghiệp xã hội sử dụng bao nhiêu phần trăm lợi nhuận sau thuế?"
    )

    assert parsed.has_temporal is False
    assert parsed.parse_error is None
