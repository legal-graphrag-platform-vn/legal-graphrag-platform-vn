from pathlib import Path

from src.parser.hierarchy_parser import parse_text
from src.parser.models import DocumentInfo

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
    assert [a.number for a in parsed.articles] == [1, 2, 17]


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


def test_clauses_and_points_under_article_17() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    art17 = parsed.articles[2]
    assert [c.number for c in art17.clauses] == [1, 2]
    clause1 = art17.clauses[0]
    assert len(clause1.points) == 2
    assert clause1.points[0].label == "a"
    assert clause1.points[1].label == "b"
    assert "Cơ quan nhà nước" in clause1.points[0].content


def test_clause_content_not_empty() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_text(text, _doc_info())
    for article in parsed.articles:
        for clause in article.clauses:
            assert clause.content.strip() != ""


def test_does_not_crash_on_empty_text() -> None:
    parsed = parse_text("", _doc_info())
    assert parsed.articles == []



def test_clean_vietnamese_spacing() -> None:
    from src.parser.hierarchy_parser import clean_vietnamese_spacing
    
    assert clean_vietnamese_spacing("Công ty trách nhi ệm h ữu h ạn") == "Công ty trách nhiệm hữu hạn"
    assert clean_vietnamese_spacing("hợp cuộc họp được triệu tập t heo quy định") == "hợp cuộc họp được triệu tập theo quy định"
    assert clean_vietnamese_spacing("Người qu ản lý doanh nghi ệp là người") == "Người quản lý doanh nghiệp là người"
    assert clean_vietnamese_spacing("điểm a, b, c, d, đ và e") == "điểm a, b, c, d, đ và e"
    assert clean_vietnamese_spacing("luật t rên p háp luật nước c ộng hòa xã hội") == "luật trên pháp luật nước cộng hòa xã hội"


def test_should_skip_line() -> None:
    from src.parser.hierarchy_parser import should_skip_line

    assert should_skip_line("4") is True
    assert should_skip_line("123") is True
    assert should_skip_line("Ký bởi: Cổng Thông tin điện tử Chính phủ") is True
    assert should_skip_line("Email: thongtinchinhphu@chinhphu.vn") is True
    assert should_skip_line("Cơ quan: Văn phòng Chính phủ") is True
    assert should_skip_line("Thời gian ký: 19.01.2015 08:56:24 +07:00") is True
    assert should_skip_line("CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014") is True
    assert should_skip_line("Điều 1. Phạm vi điều chỉnh") is False
    assert should_skip_line("1. Các doanh nghiệp.") is False


