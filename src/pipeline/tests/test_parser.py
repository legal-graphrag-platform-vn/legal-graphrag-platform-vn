from datetime import date
from pathlib import Path

import pytest

from src.pipeline.parser.hierarchy_parser import parse_text, parse_text_with_diagnostics
from src.pipeline.parser.models import (
    Article,
    Clause,
    DocumentInfo,
    ParsedDocument,
    Point,
    Section,
)
from src.shared.ontology.hierarchy import (
    normalize_part_number,
    part_id,
    subsection_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_law.txt"


def _doc_info() -> DocumentInfo:
    return DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
    )


def test_parses_two_articles() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    assert len(parsed.articles) == 3
    assert [a.number for a in parsed.articles] == ["1", "2", "17"]


def test_article_title_extracted() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    art1 = parsed.articles[0]
    assert art1.title == "Phạm vi điều chỉnh"


def test_chapter_attached_to_article() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    art1, art2, art17 = parsed.articles
    assert art1.chapter == "I"
    assert art1.chapter_title == "QUY ĐỊNH CHUNG"
    assert art17.chapter == "II"
    assert art17.chapter_title == "THÀNH LẬP DOANH NGHIỆP"


def test_parser_builds_section_hierarchy_for_supported_heading_variants() -> None:
    text = """Chương III
CÔNG TY
Mục 1. Quy định chung
Điều 46. Điều thứ nhất
MỤC 2
QUẢN TRỊ CÔNG TY
Điều 47. Điều thứ hai
Mục 3a: Chuyển tiếp
Điều 48. Điều thứ ba
"""

    parsed = parse_text(text, _doc_info())

    assert [
        (section.chapter, section.number, section.title) for section in parsed.sections
    ] == [
        ("III", "1", "Quy định chung"),
        ("III", "2", "QUẢN TRỊ CÔNG TY"),
        ("III", "3a", "Chuyển tiếp"),
    ]
    assert [article.section for article in parsed.articles] == ["1", "2", "3a"]


def test_parser_accepts_section_without_chapter() -> None:
    parsed = parse_text("Mục 1. Quy định chung\nĐiều 1. Test", _doc_info())
    assert len(parsed.sections) == 1
    assert parsed.sections[0].number == "1"
    assert parsed.sections[0].chapter is None


def test_parser_does_not_treat_inline_section_citation_as_heading() -> None:
    parsed = parse_text(
        "Điều 1. Test\n1. Áp dụng theo Mục 1 Chương III của Luật này.",
        _doc_info(),
    )

    assert parsed.sections == []
    assert "Mục 1 Chương III" in parsed.articles[0].clauses[0].content


def test_parser_accepts_bounded_uppercase_legal_title_with_punctuation() -> None:
    title = (
        "QUY ĐỊNH VỀ DOANH NGHIỆP NẮM GIỮ TRÊN 50% VỐN ĐIỀU LỆ; "
        "QUẢN LÝ, GIÁM SÁT VÀ KIỂM TRA"
    )
    parsed = parse_text(
        f"Chương III\nTÊN CHƯƠNG\nMục 1\n{title}\nĐiều 1. Test",
        _doc_info(),
    )

    assert parsed.sections[0].title == title


@pytest.mark.parametrize(
    ("text", "expected_context"),
    [
        (
            "Phần I\nQUY ĐỊNH CHUNG\nChương I\nCHƯƠNG MỘT\nMục 1. Mục một\n"
            "Tiểu mục 1. Tiểu mục một\nĐiều 1. Nội dung",
            ("i", "I", "1", "1"),
        ),
        (
            "Phần I. Phần một\nChương I\nCHƯƠNG MỘT\nMục 1. Mục một\nĐiều 1. Nội dung",
            ("i", "I", "1", None),
        ),
        (
            "Phần thứ nhất. Phần một\nChương I\nCHƯƠNG MỘT\nĐiều 1. Nội dung",
            ("thứ nhất", "I", None, None),
        ),
        (
            "Chương I\nCHƯƠNG MỘT\nMục 1. Mục một\n"
            "Tiểu Mục 1\nTIỂU MỤC MỘT\nĐiều 1. Nội dung",
            (None, "I", "1", "1"),
        ),
        (
            "Chương I\nCHƯƠNG MỘT\nMục 1. Mục một\nĐiều 1. Nội dung",
            (None, "I", "1", None),
        ),
        (
            "Chương I\nCHƯƠNG MỘT\nĐiều 1. Nội dung",
            (None, "I", None, None),
        ),
        ("Điều 1. Nội dung", (None, None, None, None)),
    ],
)
def test_parser_supports_all_seven_canonical_article_paths(
    text: str, expected_context: tuple[str | None, str | None, str | None, str | None]
) -> None:
    parsed = parse_text(text, _doc_info())

    article = parsed.articles[0]
    assert (article.part, article.chapter, article.section, article.subsection) == (
        expected_context
    )


def test_parser_preserves_part_and_subsection_metadata() -> None:
    parsed = parse_text(
        "Phần II: Quy định chuyên ngành\nChương IV\nCHƯƠNG BỐN\n"
        "Mục 3. Quy trình\nTiểu mục 1a: Trình tự\nĐiều 10. Thực hiện",
        _doc_info(),
    )

    assert [(part.number, part.title) for part in parsed.parts] == [
        ("ii", "Quy định chuyên ngành")
    ]
    assert [
        (sub.part, sub.chapter, sub.section, sub.number, sub.title)
        for sub in parsed.subsections
    ] == [("ii", "IV", "3", "1a", "Trình tự")]


def test_parser_accepts_direct_chapter_preamble_before_section_articles() -> None:
    parsed = parse_text(
        "Chương XXIII\nCÁC TỘI PHẠM VỀ CHỨC VỤ\n"
        "Điều 352. Khái niệm tội phạm về chức vụ\n"
        "Mục 1. Các tội phạm tham nhũng\n"
        "Điều 353. Tội tham ô tài sản\n"
        "Điều 354. Tội nhận hối lộ",
        _doc_info(),
    )

    assert [article.number for article in parsed.articles] == ["352", "353", "354"]
    assert [article.section for article in parsed.articles] == [None, "1", "1"]


def test_parser_compares_preamble_articles_by_natural_legal_number() -> None:
    parsed = parse_text(
        "Chương I\nTÊN CHƯƠNG\n"
        "Điều 98. Mở đầu một\n"
        "Điều 99. Mở đầu hai\n"
        "Mục 1. Mục một\n"
        "Điều 100. Trong Mục",
        _doc_info(),
    )

    assert [article.number for article in parsed.articles] == ["98", "99", "100"]
    assert [article.section for article in parsed.articles] == [None, None, "1"]


def test_parsed_document_accepts_direct_article_after_section_articles() -> None:
    doc = ParsedDocument(
        document=_doc_info(),
        sections=[Section(number="1", title="Mục một", chapter="XXIII")],
        articles=[
            Article(
                number="353",
                title="Trong Mục",
                content_raw="Nội dung",
                chapter="XXIII",
                section="1",
            ),
            Article(
                number="354",
                title="Trực tiếp",
                content_raw="Nội dung",
                chapter="XXIII",
            ),
        ],
    )
    assert len(doc.articles) == 2


def test_parser_rejects_invalid_part_subsection_and_section_child_modes() -> None:
    with pytest.raises(ValueError, match="Subsection 1 appears before any Section"):
        parse_text("Tiểu mục 1. Tên\nĐiều 1. Nội dung", _doc_info())

    with pytest.raises(
        ValueError, match="mixes Subsection and direct Article child modes"
    ):
        parse_text(
            "Chương I\nTÊN CHƯƠNG\nMục 1. Mục\nĐiều 1. Trực tiếp\n"
            "Tiểu mục 1. Tiểu mục\nĐiều 2. Trong tiểu mục",
            _doc_info(),
        )


def test_part_and_subsection_ids_are_deterministic_and_normalized() -> None:
    assert normalize_part_number("I") == "1"
    assert normalize_part_number("1") == "1"
    assert normalize_part_number("Thứ nhất") == "1"
    assert part_id("demo", "Thứ nhất") == "demo_part1"
    assert subsection_id("demo", "III", "1", "2a") == "demo_ch3_sec1_subsec2a"


def test_clauses_and_points_under_article_17() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    art17 = parsed.articles[2]
    assert [c.number for c in art17.clauses] == ["1", "2"]
    clause1 = art17.clauses[0]
    assert len(clause1.points) == 2
    assert clause1.points[0].label == "a"
    assert clause1.points[1].label == "b"
    assert "Cơ quan nhà nước" in clause1.points[0].content


def test_parser_supports_suffixed_article_and_clause_numbers() -> None:
    parsed = parse_text(
        "Điều 5a. Điều bổ sung\n1b. Khoản bổ sung",
        _doc_info(),
    )
    assert parsed.articles[0].number == "5a"
    assert parsed.articles[0].clauses[0].number == "1b"


def test_parser_does_not_treat_phone_numbers_as_clauses() -> None:
    parsed = parse_text(
        (
            "Điều 218. Quy định chuyển tiếp\n"
            "1. Khoản thứ nhất\n"
            "2. Khoản thứ hai\n"
            "Điện thoại:\n"
            "024.6273.9468 | Fax:\n"
            "024.6273.9359"
        ),
        _doc_info(),
    )

    assert [clause.number for clause in parsed.articles[0].clauses] == ["1", "2"]


def test_clause_content_not_empty() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    for article in parsed.articles:
        for clause in article.clauses:
            assert clause.content.strip() != ""


def test_does_not_crash_on_empty_text() -> None:
    parsed = parse_text("", _doc_info())
    assert parsed.articles == []


def test_clause_merges_duplicate_point_labels() -> None:
    clause = Clause(
        number=4,
        content="Khoản 4",
        points=[
            Point(label="c", content="Bản một"),
            Point(label="c", content="Bản hai"),
        ],
    )
    assert len(clause.points) == 1
    assert clause.points[0].content == "Bản một Bản hai"


def test_parser_merges_duplicate_point_labels_in_same_clause() -> None:
    text = "Điều 1. Test\n1. Khoản\nc) Bản một\nc) Bản hai"
    parsed = parse_text(text, _doc_info())
    assert len(parsed.articles[0].clauses[0].points) == 1
    assert parsed.articles[0].clauses[0].points[0].content == "Bản một Bản hai"


def test_parser_deduplicates_identical_point_around_vbpl_annotation() -> None:
    text = (
        "Điều 1. Test\n1. Khoản\nc) Nội dung\n"
        "Điều khoản được sửa đổi, bổ sung\nc) Nội dung"
    )
    parsed = parse_text(text, _doc_info())
    assert [
        (point.label, point.content) for point in parsed.articles[0].clauses[0].points
    ] == [("c", "Nội dung")]


def test_parser_preserves_appendix_without_attaching_it_to_last_article() -> None:
    text = (
        "Điều 1. Nội dung\n1. Khoản chính\n"
        "PHỤ LỤC I\n1. Không phải khoản\na) Không phải điểm\n"
    )

    parsed = parse_text(text, _doc_info())

    assert len(parsed.articles) == 1
    assert parsed.articles[0].clauses[0].content == "Khoản chính"
    assert len(parsed.unparsed_sections) == 1
    appendix = parsed.unparsed_sections[0]
    assert appendix.heading == "PHỤ LỤC I"
    assert appendix.content_raw == "1. Không phải khoản\na) Không phải điểm"
    assert text[appendix.source_start_char : appendix.source_end_char].startswith(
        "PHỤ LỤC I"
    )


def test_parser_does_not_treat_inline_appendix_word_as_heading() -> None:
    parsed = parse_text(
        "Điều 1. Nội dung\n1. Kèm theo phụ lục và tài liệu", _doc_info()
    )
    assert parsed.unparsed_sections == []
    assert "phụ lục" in parsed.articles[0].clauses[0].content


def test_parser_source_spans_use_canonical_source_coordinates() -> None:
    text = "Điều 1. Nội dung\r\n1. Khoản\r\na) Điểm"
    parsed = parse_text(text, _doc_info())
    canonical = text.replace("\r\n", "\n")
    point = parsed.articles[0].clauses[0].points[0]
    assert canonical[point.source_start_char : point.source_end_char] == "a) Điểm"


def test_parser_keeps_structural_headings_inside_replacement_quote_in_host_article() -> (
    None
):
    text = (
        "Điều 1. Sửa đổi, bổ sung\n"
        "1. Bổ sung mục mới như sau:\n"
        "“Mục 3a\n"
        "Điều 17a. Nội dung được bổ sung\n"
        "Nội dung chi tiết.”.\n"
        "Điều 2. Điều khoản thi hành"
    )

    parsed = parse_text(text, _doc_info())

    assert [article.number for article in parsed.articles] == ["1", "2"]
    assert "Điều 17a. Nội dung được bổ sung" in parsed.articles[0].content_raw


def test_parser_does_not_merge_articles_after_mixed_typographic_quote() -> None:
    text = (
        "Điều 19. Tài khoản kế toán\n"
        '1. Bao gồm khoản “Phải thu nội bộ".\n'
        "Điều 20. Báo cáo tài chính\n"
        "1. Lập báo cáo theo quy định."
    )

    parsed, diagnostics = parse_text_with_diagnostics(text, _doc_info())

    assert [article.number for article in parsed.articles] == ["19", "20"]
    assert diagnostics.status == "PARSED_WITH_WARNINGS"
    assert [warning.code for warning in diagnostics.warnings] == [
        "UNSCOPED_QUOTE_IMBALANCE_IGNORED"
    ]


def test_parser_does_not_merge_articles_after_unclosed_ordinary_quote() -> None:
    text = (
        "Điều 6. Công ty mẹ\n"
        "1. Công ty mẹ “ Tập đoàn thực hiện quyền quản lý.\n"
        "Điều 7. Công ty con\n"
        "1. Công ty con thực hiện nghĩa vụ."
    )

    parsed, diagnostics = parse_text_with_diagnostics(text, _doc_info())

    assert [article.number for article in parsed.articles] == ["6", "7"]
    assert diagnostics.warnings[0].source_line == 2


def test_parser_recovers_headings_from_unclosed_replacement_quote() -> None:
    text = (
        "Điều 1. Sửa đổi, bổ sung\n"
        "1. Bổ sung nội dung như sau:\n"
        "“Mục 3a\n"
        "Điều 17a. Nội dung được bổ sung\n"
        "Nội dung không có dấu đóng.\n"
        "Điều 2. Điều khoản thi hành"
    )

    parsed, diagnostics = parse_text_with_diagnostics(text, _doc_info())

    assert [article.number for article in parsed.articles] == ["1", "17a", "2"]
    assert diagnostics.warnings[-1].code == "UNCLOSED_REPLACEMENT_QUOTE_IGNORED"


def test_parser_preserves_unstructured_body_in_permissive_result() -> None:
    text = "I. QUY ĐỊNH CHUNG\n1/ Phạm vi áp dụng\n2/ Đối tượng thực hiện"

    parsed, diagnostics = parse_text_with_diagnostics(text, _doc_info())

    assert parsed.articles == []
    assert diagnostics.status == "SOURCE_PRESERVED"
    assert [warning.code for warning in diagnostics.warnings] == ["NO_ARTICLE_BOUNDARY"]
    assert len(parsed.unparsed_sections) == 1
    fallback = parsed.unparsed_sections[0]
    assert fallback.section_type == "UNPARSED_BODY"
    assert fallback.content_raw == text


def test_permissive_result_preserves_source_when_hierarchy_validation_fails() -> None:
    text = (
        "Chương I\nTÊN CHƯƠNG\nMục 1. Mục\nĐiều 1. Trực tiếp\n"
        "Tiểu mục 1. Tiểu mục\nĐiều 2. Trong tiểu mục"
    )

    parsed, diagnostics = parse_text_with_diagnostics(text, _doc_info())

    assert parsed.articles == []
    assert diagnostics.status == "SOURCE_PRESERVED"
    assert diagnostics.warnings[-1].code == "HIERARCHY_VALIDATION_FALLBACK"
    assert parsed.unparsed_sections[0].content_raw == text


def test_parser_uses_explicit_source_effective_date_when_metadata_is_missing() -> None:
    parsed = parse_text(
        "Điều 1. Hiệu lực\n"
        "Nghị định này có hiệu lực thi hành từ ngày 15 tháng 11 năm 2024.",
        _doc_info().model_copy(update={"effective_from": None}),
    )

    assert parsed.document.effective_from == date(2024, 11, 15)


def test_parser_keeps_metadata_effective_date_over_quoted_source_date() -> None:
    parsed = parse_text(
        "Điều 1. Nội dung sửa đổi\n"
        "Văn bản được trích dẫn có hiệu lực thi hành từ ngày 15 tháng 11 năm 2024.",
        _doc_info().model_copy(update={"effective_from": date(2025, 1, 1)}),
    )

    assert parsed.document.effective_from == date(2025, 1, 1)


def test_clean_vietnamese_spacing() -> None:
    from src.pipeline.parser.hierarchy_parser import clean_vietnamese_spacing

    assert (
        clean_vietnamese_spacing("Công ty trách nhi ệm h ữu h ạn")
        == "Công ty trách nhiệm hữu hạn"
    )
    assert (
        clean_vietnamese_spacing("hợp cuộc họp được triệu tập t heo quy định")
        == "hợp cuộc họp được triệu tập theo quy định"
    )
    assert (
        clean_vietnamese_spacing("Người qu ản lý doanh nghi ệp là người")
        == "Người quản lý doanh nghiệp là người"
    )
    assert (
        clean_vietnamese_spacing("điểm a, b, c, d, đ và e") == "điểm a, b, c, d, đ và e"
    )
    assert (
        clean_vietnamese_spacing("luật t rên p háp luật nước c ộng hòa xã hội")
        == "luật trên pháp luật nước cộng hòa xã hội"
    )


def test_should_skip_line() -> None:
    from src.pipeline.parser.hierarchy_parser import should_skip_line

    assert should_skip_line("4") is True
    assert should_skip_line("123") is True
    assert should_skip_line("Ký bởi: Cổng Thông tin điện tử Chính phủ") is True
    assert should_skip_line("Email: thongtinchinhphu@chinhphu.vn") is True
    assert should_skip_line("Cơ quan: Văn phòng Chính phủ") is True
    assert should_skip_line("Thời gian ký: 19.01.2015 08:56:24 +07:00") is True
    assert should_skip_line("CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014") is True
    assert should_skip_line("Điều 1. Phạm vi điều chỉnh") is False
    assert should_skip_line("1. Các doanh nghiệp.") is False
