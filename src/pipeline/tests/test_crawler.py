from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.crawler.vbpl_crawler import (
    _extract_body_lines,
    _extract_metadata,
    _infer_doc_type,
    crawl_by_search,
)

FIXTURE = Path(__file__).parent / "fixtures" / "vbpl_rendered_body.txt"


def _body_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_extract_metadata_fields() -> None:
    meta = _extract_metadata(
        _body_text(), doc_id="LDN2020", number="59/2020/QH14", source_url="https://vbpl.vn/x"
    )
    assert meta.doc_id == "LDN2020"
    assert meta.title == "Luật doanh nghiệp số 59/2020/QH14"
    assert meta.status == "Hết hiệu lực một phần"
    assert meta.effective_from == date(2021, 1, 1)
    assert meta.issued_date == date(2020, 7, 1)
    assert meta.issued_by == "QUỐC HỘI"
    assert meta.doc_type == "Law"


def test_extract_body_lines_strips_nav_and_tabs() -> None:
    lines = _extract_body_lines(_body_text())
    joined = "\n".join(lines)
    assert "Trang chủ" not in joined
    assert "Tải về" not in joined
    assert "Điều 1. Phạm vi điều chỉnh" in joined


def test_infer_doc_type() -> None:
    assert _infer_doc_type("59/2020/QH14") == "Law"
    assert _infer_doc_type("01/2021/NĐ-CP") == "Decree"
    assert _infer_doc_type("01/2021/TT-BKHDT") == "Circular"


@patch("src.crawler.vbpl_crawler.sync_playwright")
@patch("src.crawler.vbpl_crawler.crawl_and_save")
def test_crawl_by_search_mocked(mock_crawl_and_save: MagicMock, mock_sync_playwright: MagicMock) -> None:
    # 1.   Mock playwright browser, context, page, and locator
    mock_playwright = MagicMock()
    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright
    
    mock_browser = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser
    
    mock_context = MagicMock()
    mock_browser.new_context.return_value = mock_context
    
    mock_page = MagicMock()
    mock_context.new_page.return_value = mock_page
    
    # 2.   Mock search results elements
    mock_title_el = MagicMock()
    mock_title_el.inner_text.return_value = "Luật Doanh nghiệp số 59/2020/QH14"
    
    # We mock locator() so that when it is called for title cards it returns the title locator,
    # and when it is called for the "Sau" button it returns the next button.
    # To do this safely, we make page.locator return different mocks based on arguments.
    mock_title_locator = MagicMock()
    mock_title_locator.all.return_value = [mock_title_el]
    
    mock_search_btn_locator = MagicMock()
    mock_search_btn_nth = MagicMock()
    mock_search_btn_locator.nth.return_value = mock_search_btn_nth
    
    def locator_side_effect(selector, **kwargs):
        if "DocumentCard_documentTitle__" in selector:
            return mock_title_locator
        elif "Sau" in selector:
            return mock_next_btn
        elif "button:has-text('Tìm kiếm')" in selector:
            return mock_search_btn_locator
        return MagicMock()
        
    mock_page.locator.side_effect = locator_side_effect
    
    # 3.   Mock new tab opening on title click
    mock_new_page = MagicMock()
    mock_new_page.value.url = "https://vbpl.vn/van-ban/chi-tiet/ldn2020"
    
    # Mock context.expect_page() context manager
    mock_expect_page_cm = MagicMock()
    mock_expect_page_cm.__enter__.return_value = mock_new_page
    mock_context.expect_page.return_value = mock_expect_page_cm
    
    # 4.   Run crawl_by_search
    raw_dir = Path("data/raw")
    crawl_by_search("Luật Doanh nghiệp", raw_dir, limit=1)
    
    # 5.   Verify Playwright interactions
    mock_page.fill.assert_any_call("input#keyword", "Luật Doanh nghiệp")
    mock_page.click.assert_any_call("input[type='radio'][value='title']")
    mock_page.click.assert_any_call("label:has-text('Chính xác cụm từ trên')")
    mock_page.locator.assert_any_call("button:has-text('Tìm kiếm')")
    mock_search_btn_locator.nth.assert_called_once_with(-1)
    mock_search_btn_nth.click.assert_called_once_with(force=True)
    
    # 6.   Verify crawl_and_save was called with correct parameters
    mock_crawl_and_save.assert_called_once_with(
        "https://vbpl.vn/van-ban/chi-tiet/ldn2020",
        "L59_2020",
        "59/2020/QH14",
        raw_dir
    )
