

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.crawler.models import DocumentMetadata

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_EFFECTIVE_FROM_RE = re.compile(r"Ngày có hiệu lực:\s*\n?\s*(\d{2})/(\d{2})/(\d{4})")
_ISSUED_DATE_RE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
_STATUS_KEYWORDS = [
    "Hết hiệu lực một phần",
    "Hết hiệu lực toàn bộ",
    "Còn hiệu lực",
    "Chưa có hiệu lực",
]
_ISSUERS = ["QUỐC HỘI", "CHÍNH PHỦ", "THỦ TƯỚNG CHÍNH PHỦ", "ỦY BAN THƯỜNG VỤ QUỐC HỘI"]

# Tiền tố ký hiệu số văn bản -> loại văn bản (ADR doc_type enum). Khớp dài nhất trước
# (vd "ND-CP" trước "ND") để tránh nhận nhầm số hiệu ghép.
_DOC_TYPE_BY_PREFIX = [
    ("ND-CP", "Decree"),
    ("QH", "Law"),
    ("TT", "Circular"),
    ("NQ", "Resolution"),
    ("QD", "Decision"),
]


def _infer_doc_type(number: str) -> str:
    last_segment = number.split("/")[-1].upper().replace("Đ", "D")
    for prefix, doc_type in _DOC_TYPE_BY_PREFIX:
        if last_segment.startswith(prefix):
            return doc_type
    return "Law"


def _parse_vn_date(day: str, month: str, year: str) -> date:
    return date(int(year), int(month), int(day))


def _extract_metadata(body_text: str, doc_id: str, number: str, source_url: str) -> DocumentMetadata:
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    number_prefix = number.split("/")[0]

    title = next(
        (line for line in lines if "số" in line.lower() and number_prefix in line),
        doc_id,
    )
    status = next((line for line in lines if line in _STATUS_KEYWORDS), "active")
    issued_by = next((line for line in lines if line in _ISSUERS), None)

    effective_from = None
    if m := _EFFECTIVE_FROM_RE.search(body_text):
        effective_from = _parse_vn_date(*m.groups())

    issued_date = None
    if m := _ISSUED_DATE_RE.search(body_text):
        issued_date = _parse_vn_date(*m.groups())

    return DocumentMetadata(
        doc_id=doc_id,
        title=title,
        number=number,
        doc_type=_infer_doc_type(number),
        issued_by=issued_by,
        issued_date=issued_date,
        effective_from=effective_from,
        effective_to=None,
        status=status,
        source_url=source_url,
    )


def _extract_body_lines(full_text: str) -> list[str]:
    """Cắt phần nav/breadcrumb lặp ở đầu trang, giữ lại nội dung văn bản thật.

    vbpl.vn render cụm tab "Nội dung | Thuộc tính | Lược đồ | Văn bản gốc | Tải về"
    hai lần (breadcrumb rồi tới heading khối nội dung) -> nội dung văn bản thật nằm
    SAU lần xuất hiện cuối cùng của dòng "Tải về".
    """
    lines = full_text.splitlines()
    last_tai_ve = -1
    for i, line in enumerate(lines):
        if line.strip() == "Tải về":
            last_tai_ve = i
    if last_tai_ve == -1:
        logger.warning("Không tìm thấy marker 'Tải về' trên trang — dùng toàn bộ text làm nội dung.")
        return lines
    
    body_lines = lines[last_tai_ve + 1 :]
    
    # 1.    Tìm vị trí bắt đầu thực sự của Luật (Chương đầu tiên, Phần đầu tiên, hoặc Điều 1).
    start_index = -1
    start_pattern = re.compile(
        r"^(Chương\s+[IVXLCDM\d]+|Phần\s+(\d+|[IVXLCDM]+|thứ\s+\w+)|Điều\s+1\b)",
        re.IGNORECASE
    )
    for i, line in enumerate(body_lines):
        if start_pattern.match(line.strip()):
            start_index = i
            break
            
    if start_index != -1:
        body_lines = body_lines[start_index:]
        
    # 2.    Tìm vị trí bắt đầu của Điều luật cuối cùng để làm mốc an toàn.
    search_start_index = 0
    for i in range(len(body_lines) - 1, -1, -1):
        if re.match(r"^Điều\s+\d+\.", body_lines[i].strip()):
            search_start_index = i
            break
            
    # 3.    Nếu không tìm thấy Điều nào, mặc định tìm ở nửa sau văn bản.
    if search_start_index == 0:
        search_start_index = len(body_lines) // 2
        
    # 4.    Danh sách các marker chữ ký đặc trưng ở cuối văn bản luật.
    _SIGNATURE_MARKERS = {
        "CHỦ TỊCH QUỐC HỘI",
        "THỦ TƯỚNG CHÍNH PHỦ",
        "KT. THỦ TƯỚNG",
        "KÝ THAY",
        "KT. BỘ TRƯỞNG",
        "QUYỀN CHỦ TỊCH",
        "(Đã ký)",
        "(đã ký)",
        "TM. CHÍNH PHỦ",
        "TM. QUỐC HỘI",
        "TM. ỦY BAN THƯỜNG VỤ QUỐC HỘI",
        "THỦ TƯỚNG",
        "BỘ TRƯỞNG",
        "CHỦ TỊCH",
        "NƠI NHẬN:",
        "Nơi nhận:",
        "Nơi nhận",
    }
    
    truncate_index = -1
    for i in range(search_start_index, len(body_lines)):
        line_clean = body_lines[i].strip()
        line_clean_lower = line_clean.lower()
        is_redundant = (
            line_clean == "CƠ SỞ DỮ LIỆU QUỐC GIA VỀ PHÁP LUẬT"
            or line_clean_lower == "mục lục"
            or line_clean in _SIGNATURE_MARKERS
            or line_clean_lower.startswith("luật này được quốc hội")
            or line_clean_lower.startswith("luật này đã được quốc hội")
            or line_clean_lower.startswith("nghị định này được")
            or any(line_clean_lower.startswith(m) for m in ["kt.", "tm.", "ký thay", "ký thay.", "nơi nhận", "nơi nhận:"])
        )
        if is_redundant:
            truncate_index = i
            break
            
    if truncate_index != -1:
        body_lines = body_lines[:truncate_index]
        
    return body_lines


def fetch_document(url: str, doc_id: str, number: str, timeout_ms: int = 30000) -> tuple[str, DocumentMetadata]:
    """Render trang chi tiết vbpl.vn bằng Playwright, trả về (full_text, metadata).

    `full_text` là nội dung văn bản pháp luật thuần, sẵn sàng làm input cho
    `parser.hierarchy_parser.parse_text()`. Dùng `new_context` với user-agent/locale
    thật thay vì `browser.new_page()` mặc định vì vbpl.vn có WAF chặn request có
    fingerprint headless trần (trả về "Web Page Blocked! Attack ID: ...").
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="vi-VN",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        browser.close()

    metadata = _extract_metadata(body_text, doc_id=doc_id, number=number, source_url=url)
    full_text = "\n".join(_extract_body_lines(body_text))
    return full_text, metadata


def crawl_and_save(url: str, doc_id: str, number: str, raw_dir: Path) -> DocumentMetadata:
    """Crawl + lưu `data/raw/<doc_id>/source.txt` + `metadata.json`."""
    full_text, metadata = fetch_document(url, doc_id=doc_id, number=number)

    out_dir = raw_dir / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source.txt").write_text(full_text, encoding="utf-8")
    (out_dir / "metadata.json").write_text(
        metadata.model_dump_json(by_alias=True, indent=2, exclude_none=True),
        encoding="utf-8",
    )
    logger.info("Đã lưu %s vào %s", doc_id, out_dir)
    return metadata


def crawl_by_search(
    query: str,
    raw_dir: Path,
    limit: int = 10,
    timeout_ms: int = 30000,
) -> list[DocumentMetadata]:
    """Crawl hàng loạt tài liệu từ kết quả tìm kiếm trên vbpl.vn."""
    logger.info("Bắt đầu crawl hàng loạt dựa trên tìm kiếm với từ khóa: '%s', giới hạn: %d", query, limit)
    
    # 1.   Phần phân tích trích xuất doc_id và số hiệu từ tiêu đề
    def infer_doc_id_and_number(title_text: str) -> tuple[str | None, str | None]:
        num_match = re.search(r"(\d+(?:/\d+)?/[A-ZĐa-z0-9\-]+)", title_text)
        if not num_match:
            return None, None
            
        number = num_match.group(1)
        parts = number.split("/")
        num_part = parts[0]
        year_part = parts[1] if len(parts) > 1 else "unknown"
        
        title_lower = title_text.lower()
        if "luật" in title_lower:
            prefix = "L"
        elif "nghị định" in title_lower:
            prefix = "ND"
        elif "thông tư" in title_lower:
            prefix = "TT"
        elif "nghị quyết" in title_lower:
            prefix = "NQ"
        elif "quyết định" in title_lower:
            prefix = "QD"
        else:
            prefix = "DOC"
            
        doc_id = f"{prefix}{num_part}_{year_part}"
        return doc_id, number

    results_metadata: list[DocumentMetadata] = []
    links_to_crawl: list[tuple[str, str, str]] = []  # (url, doc_id, number)

    # 2.   Khởi động Playwright để tìm kiếm các văn bản
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="vi-VN",
        )
        page = context.new_page()
        
        url = "https://vbpl.vn/van-ban/trung-uong"
        logger.info("Đang điều hướng đến trang tìm kiếm: %s", url)
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(3000)
        
        # 3.   Điền từ khóa và ẩn các gợi ý tìm kiếm tự động để tránh che khuất click
        page.fill("input#keyword", query)
        page.wait_for_timeout(1000)
        page.evaluate("""
            () => {
                const els = document.querySelectorAll('*');
                els.forEach(el => {
                    if (el.className && typeof el.className === 'string' && el.className.toLowerCase().includes('suggestion')) {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.pointerEvents = 'none';
                    }
                });
            }
        """)
        page.wait_for_timeout(500)
        page.click("input[type='radio'][value='title']")
        page.wait_for_timeout(500)
        page.click("label:has-text('Chính xác cụm từ trên')")
        page.wait_for_timeout(500)
        
        # 4.   Nhấn tìm kiếm và chờ kết quả
        search_btn = page.locator("button:has-text('Tìm kiếm')").nth(-1)
        search_btn.click(force=True)
        logger.info("Chờ tải kết quả tìm kiếm...")
        page.wait_for_selector("div[class*='DocumentCard_documentTitle__']", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        
        # 5.   Lặp qua các trang để thu thập đủ số lượng URL mong muốn
        while len(links_to_crawl) < limit:
            title_locators = page.locator("div[class*='DocumentCard_documentTitle__']").all()
            if not title_locators:
                break
                
            for title_el in title_locators:
                if len(links_to_crawl) >= limit:
                    break
                    
                title_text = title_el.inner_text().strip()
                doc_id, number = infer_doc_id_and_number(title_text)
                
                if not doc_id or not number:
                    continue
                    
                with context.expect_page() as new_page_info:
                    title_el.click()
                new_page = new_page_info.value
                new_page.wait_for_timeout(1000)
                detail_url = new_page.url
                new_page.close()
                
                links_to_crawl.append((detail_url, doc_id, number))
                logger.info("Đã thu thập URL: %s | ID: %s", detail_url, doc_id)
                
            if len(links_to_crawl) >= limit:
                break
                
            # 6.   Chuyển sang trang kết quả tiếp theo nếu chưa đạt giới hạn
            next_btn = page.locator("button:has-text('Sau')")
            if next_btn.is_visible() and next_btn.is_enabled():
                logger.info("Đang chuyển sang trang kết quả tiếp theo...")
                next_btn.click()
                page.wait_for_timeout(3000)
                page.wait_for_selector("div[class*='DocumentCard_documentTitle__']", timeout=timeout_ms)
            else:
                logger.info("Đã đến trang kết quả cuối cùng.")
                break
                
        browser.close()

    # 7.   Crawl và lưu nội dung từng tài liệu đã tìm thấy
    for url_val, doc_id_val, number_val in links_to_crawl:
        try:
            metadata = crawl_and_save(url_val, doc_id_val, number_val, raw_dir)
            results_metadata.append(metadata)
        except Exception as e:
            logger.error("Lỗi khi crawl tài liệu %s từ %s: %s", doc_id_val, url_val, e)
            
    return results_metadata

