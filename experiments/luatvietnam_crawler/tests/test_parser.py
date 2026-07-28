from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from experiments.luatvietnam_crawler.errors import (
    ContentUnavailableError,
    ParseError,
    UnsupportedUrlError,
)
from experiments.luatvietnam_crawler.parser import (
    page_url,
    parse_detail_metadata,
    parse_document,
    parse_search_page_metadata,
    parse_search_results,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "Exp"


def test_page_url_preserves_duplicate_filters_and_replaces_page_index() -> None:
    source = (
        "https://luatvietnam.vn/van-ban/tim-van-ban.html?"
        "DocTypeIds=7&DocTypeIds=58&search=&search=&PageSize=100&PageIndex=1"
    )

    result = page_url(source, 3)
    pairs = parse_qsl(urlsplit(result).query, keep_blank_values=True)

    assert pairs.count(("DocTypeIds", "7")) == 1
    assert pairs.count(("DocTypeIds", "58")) == 1
    assert pairs.count(("search", "")) == 2
    assert ("PageSize", "100") in pairs
    assert ("PageIndex", "3") in pairs


def test_page_url_rejects_unapproved_host() -> None:
    with pytest.raises(UnsupportedUrlError):
        page_url("https://example.com/search?PageIndex=1", 1)


def test_page_url_normalizes_both_page_size_parameters() -> None:
    source = (
        "https://luatvietnam.vn/van-ban/tim-van-ban.html?"
        "DocTypeIds=7&PagSize=20&PageSize=50&PageIndex=1"
    )

    result = page_url(source, 3, page_size=100)
    pairs = parse_qsl(urlsplit(result).query, keep_blank_values=True)

    assert ("DocTypeIds", "7") in pairs
    assert pairs.count(("PageSize", "100")) == 1
    assert pairs.count(("PagSize", "100")) == 1
    assert pairs.count(("PageIndex", "3")) == 1


def test_parse_search_page_metadata_uses_total_and_selected_page_size() -> None:
    html = """
    <div id="search_results">
      <div class="block-text-resut"><div class="s-text1">
        <span>Có <strong>3.353</strong> văn bản</span>
        <span>; loại văn bản: </span><strong>Luật, Nghị định, Văn bản hợp nhất</strong>
        <span>; cơ quan ban hành: </span><strong>Quốc hội, Chính phủ</strong>
        <span>; lĩnh vực:</span><strong>Doanh nghiệp</strong>
        <span>; ngôn ngữ: </span><strong>Tiếng Việt</strong>
      </div></div>
    </div>
    <div class="pagination padding">
      <div class="pag-select"><select>
        <option>20 kết quả</option>
        <option selected="active" data-url="/van-ban/tim-van-ban.html?PageSize=100&amp;PageIndex=1&amp;PagSize=100">100 kết quả</option>
      </select></div>
      <span class="page-numbers ajax active" title="Trang 1">1</span>
      <a class="page-numbers ajax" title="Trang 2" href="/van-ban/tim-van-ban.html?PageSize=100&amp;PageIndex=2&amp;PagSize=100">2</a>
      <a class="page-numbers ajax" title="Trang 3" href="/van-ban/tim-van-ban.html?PageSize=100&amp;PageIndex=3&amp;PagSize=100">3</a>
      <a class="page-numbers ajax" title="Trang 4">4</a>
      <a class="page-numbers ajax" title="Trang 5">5</a>
    </div>
    """

    metadata = parse_search_page_metadata(html)

    assert metadata is not None
    assert metadata.total_results == 3353
    assert metadata.page_size == 100
    assert metadata.current_page == 1
    assert metadata.total_pages == 34
    assert metadata.visible_page_indexes == (1, 2, 3, 4, 5)
    assert metadata.next_page == 2
    assert metadata.document_types == ("Luật", "Nghị định", "Văn bản hợp nhất")
    assert metadata.issuers_raw == "Quốc hội, Chính phủ"
    assert metadata.fields == ("Doanh nghiệp",)
    assert metadata.language == "Tiếng Việt"


def test_parse_search_page_metadata_does_not_add_page_when_evenly_divisible() -> None:
    html = """
    <div id="search_results"><div class="block-text-resut"><div class="s-text1">
      Có <strong>200</strong> văn bản; loại văn bản: Luật;
      cơ quan ban hành: Quốc hội; lĩnh vực: Doanh nghiệp; ngôn ngữ: Tiếng Việt
    </div></div></div>
    <div class="pagination"><div class="pag-select"><select>
      <option selected="active">100 kết quả</option>
    </select></div><span class="page-numbers active" title="Trang 1">1</span></div>
    """

    metadata = parse_search_page_metadata(html)

    assert metadata is not None
    assert metadata.total_pages == 2


def test_parse_search_page_metadata_keeps_one_visited_page_for_empty_results() -> None:
    html = """
    <div id="search_results"><div class="block-text-resut"><div class="s-text1">
      Có 0 văn bản; loại văn bản: Luật; cơ quan ban hành: Quốc hội;
      lĩnh vực: Doanh nghiệp; ngôn ngữ: Tiếng Việt
    </div></div></div>
    <div class="pagination"><div class="pag-select"><select>
      <option selected="active">100 kết quả</option>
    </select></div><span class="page-numbers active" title="Trang 1">1</span></div>
    """

    metadata = parse_search_page_metadata(html)

    assert metadata is not None
    assert metadata.total_results == 0
    assert metadata.total_pages == 1


def test_parse_search_page_metadata_rejects_inconsistent_pagination_link() -> None:
    html = """
    <div id="search_results"><div class="block-text-resut"><div class="s-text1">
      Có 201 văn bản; loại văn bản: Luật; cơ quan ban hành: Quốc hội;
      lĩnh vực: Doanh nghiệp; ngôn ngữ: Tiếng Việt
    </div></div></div>
    <div class="pagination"><div class="pag-select"><select>
      <option selected="active">100 kết quả</option>
    </select></div>
    <span class="page-numbers active" title="Trang 1">1</span>
    <a class="page-numbers" title="Trang 2"
       href="/van-ban/tim-van-ban.html?PageSize=50&amp;PageIndex=3">2</a>
    </div>
    """

    with pytest.raises(ParseError, match="title page 2"):
        parse_search_page_metadata(html)


def test_parse_search_results_deduplicates_and_ignores_navigation() -> None:
    html = """
    <article class="art-search"><h2 class="doc-title">
      <a href="/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html">Luật doanh nghiệp</a>
    </h2></article>
    <article class="art-search"><h2 class="doc-title">
      <a href="https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html?x=1">Duplicate</a>
    </h2></article>
    <a href="/van-ban/tim-van-ban.html?PageIndex=2">Trang sau</a>
    <a href="/tin-phap-luat/tim-kiem-thong-minh-230-108786-article.html">News article</a>
    <a href="https://other.example/document-12345-d1.html">External</a>
    """

    results = parse_search_results(
        html, "https://luatvietnam.vn/van-ban/tim-van-ban.html"
    )

    assert [(item.external_id, item.title) for item in results] == [
        ("186270", "Luật doanh nghiệp")
    ]
    assert results[0].url.endswith("/luat-doanh-nghiep-2020-186270-d1.html")
    assert results[0].detail_variant == "d1"
    assert results[0].source_kind == "issued_document"


def test_parse_search_results_matches_all_ui_card_variants_only() -> None:
    html = """
    <a href="/outside/unrelated-999999-d1.html">Link ngoài danh sách</a>
    <article class="art-search"><h2 class="doc-title">
      <a href="/doanh-nghiep/issued-100001-d1.html">Văn bản đã ban hành</a>
    </h2></article>
    <article class="art-search"><h2 class="doc-title">
      <a href="/thue/consolidated-100002-d5.html">Văn bản hợp nhất</a>
    </h2></article>
    <article class="art-search"><h3 class="doc-title">
      <a href="/doanh-nghiep/draft-100003-d10.html">Dự thảo văn bản</a>
    </h3></article>
    """

    results = parse_search_results(
        html, "https://luatvietnam.vn/van-ban/tim-van-ban.html"
    )

    assert [
        (item.external_id, item.detail_variant, item.source_kind) for item in results
    ] == [
        ("100001", "d1", "issued_document"),
        ("100002", "d5", "consolidated_document"),
        ("100003", "d10", "draft_document"),
    ]


def test_parse_document_emits_experimental_metadata_and_full_text() -> None:
    html = """
    <html><body>
      <h1>Luật Doanh nghiệp số 59/2020/QH14</h1>
      <table>
        <tr><th>Số hiệu:</th><td>59/2020/QH14</td></tr>
        <tr><th>Cơ quan ban hành:</th><td>Quốc hội</td></tr>
        <tr><th>Ngày ban hành:</th><td>17/06/2020</td></tr>
        <tr><th>Ngày có hiệu lực:</th><td>01/01/2021</td></tr>
        <tr><th>Tình trạng hiệu lực:</th><td>Còn hiệu lực</td></tr>
      </table>
      <div id="tab-noi-dung">
        QUỐC HỘI
        Đang theo dõi
        Điều 1. Phạm vi điều chỉnh
        Theo dõi văn bản
        Luật này quy định về việc thành lập doanh nghiệp.
        Điều 2. Đối tượng áp dụng
        Doanh nghiệp và cơ quan có liên quan.
      </div>
    </body></html>
    """

    document = parse_document(
        html,
        "https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html",
    )

    assert document.raw_doc_code == "LTV_186270"
    assert document.candidate_graph_id == "l_59_2020"
    assert document.doc_type == "Law"
    assert document.number == "59/2020/QH14"
    assert document.issuer_name == "Quốc hội"
    assert document.issuer_branch == "LEGISLATIVE"
    assert document.effective_from.isoformat() == "2021-01-01"
    assert document.legal_status == "ACTIVE"
    assert document.source_text.count("Điều") == 2
    assert "Đang theo dõi" not in document.source_text
    assert "Theo dõi văn bản" not in document.source_text
    assert document.metadata()["experimental"] is True


def test_parse_document_marks_only_semantic_reference_spans() -> None:
    html = """
    <h1>Luật Doanh nghiệp số 59/2020/QH14</h1>
    <table><tr><th>Số hiệu:</th><td>59/2020/QH14</td></tr></table>
    <div class="the-document-body">
      <p>Điều 1. Phạm vi điều chỉnh</p>
      <p>Các doanh nghiệp quy định tại
        <span class="noi-dung-tham-chieu text-link">Khoản 2 Điều 5 Nghị định số 57/2026/NĐ-CP</span>
        và <span class="emphasis">doanh nghiệp khác</span>.</p>
      <span class="tooltip-button" data-role="customer-doc-item-follow-button">
        <span class="bg-theo-doi">Đang theo dõi</span>
      </span>
    </div>
    """

    document = parse_document(
        html,
        "https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html",
    )

    assert (
        "Các doanh nghiệp quy định tại "
        "[Khoản 2 Điều 5 Nghị định số 57/2026/NĐ-CP] và doanh nghiệp khác."
        in document.source_text
    )
    assert "[doanh nghiệp khác]" not in document.source_text
    assert "Đang theo dõi" not in document.source_text
    assert document.reference_marker_count == 1
    assert document.metadata()["content"]["reference_marker_count"] == 1


def test_parse_document_saves_usable_body_without_article_markers() -> None:
    html = """
    <h1>Quyết định số 10/2026/QĐ-TTg</h1>
    <table><tr><th>Số hiệu:</th><td>10/2026/QĐ-TTg</td></tr></table>
    <div class="the-document-body">
      <p>Phê duyệt chương trình hỗ trợ doanh nghiệp nhỏ và vừa.</p>
      <p>Quyết định này có hiệu lực kể từ ngày ký.</p>
    </div>
    """

    document = parse_document(
        html,
        "https://luatvietnam.vn/doanh-nghiep/quyet-dinh-10-2026-100001-d1.html",
    )

    assert document.article_count == 0
    assert document.source_text.startswith("Phê duyệt chương trình")
    assert document.metadata()["content"]["html_full_text_available"] is True


def test_parse_document_fails_when_legal_body_is_missing() -> None:
    html = """
    <h1>Luật Doanh nghiệp số 59/2020/QH14</h1>
    <table><tr><th>Số hiệu:</th><td>59/2020/QH14</td></tr></table>
    """

    with pytest.raises(ParseError, match="Legal body"):
        parse_document(
            html,
            "https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html",
        )


def test_parse_document_reports_html_full_text_not_published() -> None:
    html = """
    <h1>Quyết định 2180/QĐ-BGDĐT</h1>
    <table><tr><th>Số hiệu:</th><td>2180/QĐ-BGDĐT</td></tr></table>
    <div class="the-document-body doc-summary">
      Nội dung tóm tắt đang được cập nhật, Quý khách vui lòng quay lại sau!
    </div>
    <div class="the-document-body">
      Văn bản này đang cập nhật nội dung.
      Mời quý khách xem nội dung văn bản dưới dạng file PDF.
    </div>
    """

    with pytest.raises(ContentUnavailableError, match="not published HTML full text"):
        parse_document(
            html,
            "https://luatvietnam.vn/khoa-hoc/quyet-dinh-2180-qd-bgddt-441810-d1.html",
        )


def test_parse_detail_metadata_from_saved_real_page() -> None:
    fixture = next(FIXTURE_DIR.glob("*.html"))
    html = fixture.read_text(encoding="utf-8")
    url = (
        "https://luatvietnam.vn/doanh-nghiep/"
        "thong-tu-108-2026-tt-btc-huong-dan-ke-toan-co-phan-hoa-"
        "doanh-nghiep-nha-nuoc-441828-d1.html"
    )

    metadata = parse_detail_metadata(html, url)
    payload = metadata.as_dict()

    assert metadata.external_id == "441828"
    assert metadata.number == "108/2026/TT-BTC"
    assert metadata.document_type_raw == "Thông tư"
    assert metadata.doc_type == "Circular"
    assert metadata.issuer_name == "Bộ Tài chính"
    assert metadata.issuer_branch == "EXECUTIVE"
    assert metadata.signer == "Tạ Anh Tuấn"
    assert metadata.abstract == (
        "Hướng dẫn kế toán cổ phần hóa doanh nghiệp do Nhà nước nắm giữ "
        "100% vốn điều lệ"
    )
    assert metadata.issued_date.isoformat() == "2026-07-24"
    assert metadata.application_raw == "Đã biết"
    assert metadata.effective_from is None
    assert metadata.effective_to_raw == "Đang cập nhật"
    assert metadata.effective_to is None
    assert metadata.status_raw == "Đã biết"
    assert metadata.legal_status is None
    assert metadata.gazette_number_raw == "Đang cập nhật"
    assert metadata.gazette_number is None
    assert metadata.gazette_date_raw == "Đang cập nhật"
    assert metadata.gazette_date is None
    assert metadata.fields == ("Doanh nghiệp", "Kế toán-Kiểm toán")
    assert payload["page_updated_at"] == "2026-07-28T15:36:00+07:00"
    assert payload["open_graph"]["url"] == url
    assert payload["content"]["html_full_text_available"] is True
    assert payload["content"]["article_count"] > 0
    assert payload["content"]["character_count"] > 10_000
    assert payload["content"]["serializer_version"] == "luatvietnam-detail-v2"
    assert payload["content"]["reference_marker_count"] >= 1


def test_parse_saved_real_page_preserves_reference_marker_and_removes_ui() -> None:
    fixture = next(FIXTURE_DIR.glob("*.html"))
    html = fixture.read_text(encoding="utf-8")
    url = (
        "https://luatvietnam.vn/doanh-nghiep/"
        "thong-tu-108-2026-tt-btc-huong-dan-ke-toan-co-phan-hoa-"
        "doanh-nghiep-nha-nuoc-441828-d1.html"
    )

    document = parse_document(html, url)

    assert "[Khoản 2 Điều 5 Nghị định số 57/2026/NĐ-CP]" in document.source_text
    assert "Đang theo dõi" not in document.source_text
    assert "Theo dõi văn bản" not in document.source_text
