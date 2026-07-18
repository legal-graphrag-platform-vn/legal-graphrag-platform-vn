from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from src.pipeline.crawler.models import DocumentMetadata

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_EFFECTIVE_FROM_RE = re.compile(r"Ngày có hiệu lực:\s*\n?\s*(\d{2})/(\d{2})/(\d{4})")
_ISSUED_DATE_RE = re.compile(
    r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE
)
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


def _extract_metadata(
    body_text: str, doc_id: str, number: str, source_url: str
) -> DocumentMetadata:
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
    """Bỏ phần điều hướng và mục lục ở cuối, giữ trọn nội dung văn bản thật.

    vbpl.vn render cụm tab "Nội dung | Thuộc tính | Lược đồ | Văn bản gốc | Tải về"
    hai lần (breadcrumb rồi tới heading khối nội dung) -> nội dung văn bản thật nằm
    SAU lần xuất hiện cuối cùng của dòng "Tải về". Phần mở đầu, lời dẫn, chữ ký
    và nơi nhận đều thuộc raw text nên không được cắt bỏ.
    """
    # 1.   Tách văn bản thành các dòng và tìm dòng "Tải về" cuối cùng
    lines = full_text.splitlines()
    last_tai_ve = -1
    for i, line in enumerate(lines):
        if line.strip() == "Tải về":
            last_tai_ve = i
    if last_tai_ve == -1:
        logger.warning(
            "Không tìm thấy marker 'Tải về' trên trang — dùng toàn bộ text làm nội dung."
        )
        body_lines = lines
    else:
        body_lines = lines[last_tai_ve + 1 :]

    # 2.   vbpl.vn có thể nối một mục lục điều khoản sau toàn văn. Chỉ cắt heading
    # "Mục lục" xuất hiện sau ít nhất một Điều để không nhầm một heading thuộc
    # chính văn ở đầu tài liệu và vô tình làm mất nội dung.
    first_article_index = -1
    for i, line in enumerate(body_lines):
        if re.match(r"^Điều\s+\d+\b", line.strip(), re.IGNORECASE):
            first_article_index = i
            break

    if first_article_index != -1:
        # 3.   Chỉ cắt mục lục trailing. Phụ lục là nội dung pháp lý và được parser
        # bảo toàn dưới dạng unparsed section cho migration ontology sau này.
        cutoff_index = None
        for i in range(first_article_index + 1, len(body_lines)):
            line_clean = body_lines[i].strip()
            line_clean_lower = line_clean.lower()
            if line_clean_lower == "mục lục":
                cutoff_index = i
                break
        if cutoff_index is not None:
            body_lines = body_lines[:cutoff_index]

    # 3.   Loại bỏ các marker chú thích chỉnh sửa
    annotation_markers = {"Điều khoản được sửa đổi, bổ sung", "Điều khoản được bổ sung"}
    return [line for line in body_lines if line.strip() not in annotation_markers]


def fetch_document(
    url: str, doc_id: str, number: str, timeout_ms: int = 30000
) -> tuple[str, DocumentMetadata]:
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

    metadata = _extract_metadata(
        body_text, doc_id=doc_id, number=number, source_url=url
    )
    full_text = "\n".join(_extract_body_lines(body_text))
    return full_text, metadata


def _make_tab_url(base_url: str, tab_name: str) -> str:
    """Tạo URL cho tab tương ứng (thuoc-tinh hoặc luoc-do)."""
    # 1.   Kiểm tra xem URL đã chứa query parameter hay chưa
    if "?" in base_url:
        if "tabs=" in base_url:
            # 2.   Nếu đã có tham số tabs, thực hiện thay thế bằng regex
            return re.sub(r"tabs=[^&]+", f"tabs={tab_name}", base_url)
        return f"{base_url}&tabs={tab_name}"
    return f"{base_url}?tabs={tab_name}"


def parse_properties_html(html: str) -> dict[str, str]:
    """Phân tích HTML trang Thuộc tính thành cấu trúc key-value JSON."""
    if not html:
        return {}

    # 1.   Khởi tạo BeautifulSoup để parse DOM
    soup = BeautifulSoup(html, "html.parser")
    properties = {}

    # 2.   Tìm tên văn bản (tiêu đề) từ tiêu đề mô tả hoặc thẻ h1 đầu tiên
    title_el = (
        soup.find(class_="ant-descriptions-title")
        or soup.find(class_=lambda c: c and "lawDocumentHeader_title" in c)
        or soup.find("h1")
    )
    if title_el:
        doc_title = re.sub(r"\s+", " ", title_el.get_text()).strip()
        if doc_title:
            properties["Văn bản"] = doc_title

    # 3.   Tìm các thẻ mô tả thuộc tính của Ant Design
    items = soup.find_all(class_="ant-descriptions-item")
    for item in items:
        label_el = item.find(class_="ant-descriptions-item-label")
        content_el = item.find(class_="ant-descriptions-item-content")
        if label_el and content_el:
            label = re.sub(r"\s+", " ", label_el.get_text()).strip()
            content = re.sub(r"\s+", " ", content_el.get_text()).strip()
            if label:
                properties[label] = content

    # 4.   Fallback trong trường hợp cấu trúc trang thay đổi thành table truyền thống
    if len(properties) <= 1:  # Chỉ có mỗi field "Văn bản" hoặc trống
        table = soup.find("table")
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) == 2:
                    k = re.sub(r"\s+", " ", cells[0].get_text()).strip()
                    v = re.sub(r"\s+", " ", cells[1].get_text()).strip()
                    properties[k] = v

    return properties


def parse_diagram_html(html: str) -> dict[str, list[str]]:
    """Phân tích HTML trang Lược đồ thành cấu trúc danh sách liên kết, bỏ qua VĂN BẢN ĐANG XEM."""
    if not html:
        return {}

    # 1.   Khởi tạo BeautifulSoup để parse DOM lược đồ
    soup = BeautifulSoup(html, "html.parser")
    relations = {}

    # 2.   Xác định phân vùng hiển thị lược đồ (active tab panel)
    panel = soup.find(id="rc-tabs-0-panel-luoc-do") or soup.find(
        class_="ant-tabs-tabpane-active"
    )
    search_root = panel if panel else soup

    # 3.   Lặp qua các ant-card (mỗi card biểu diễn một loại quan hệ)
    cards = search_root.find_all(class_="ant-card")
    for card in cards:
        card_text = card.get_text()

        # 4.   Bỏ qua card chứa "VĂN BẢN ĐANG XEM" theo yêu cầu
        if "VĂN BẢN ĐANG XEM" in card_text:
            continue

        # 5.   Trích xuất tiêu đề của loại quan hệ
        title_el = card.find(
            "span",
            class_=lambda c: c and any(x in c for x in ["text-[#2A3034]", "font-bold"]),
        )
        if not title_el:
            title_el = card.find("span")

        if not title_el:
            continue

        relation_title = re.sub(r"\s+", " ", title_el.get_text()).strip()
        if not relation_title or relation_title == "--":
            continue

        # 6.   Trích xuất danh sách tiêu đề các văn bản liên kết trong card
        doc_links = []
        for li in card.find_all("li"):
            a_el = li.find("a")
            if a_el:
                doc_title = re.sub(r"\s+", " ", a_el.get_text()).strip()
                if doc_title and doc_title != "--":
                    doc_links.append(doc_title)
            else:
                li_text = re.sub(r"\s+", " ", li.get_text()).strip()
                if li_text and li_text != "--":
                    doc_links.append(li_text)

        relations[relation_title] = doc_links

    return relations


def fetch_document_all_tabs(
    url: str,
    doc_id: str,
    number: str,
    timeout_ms: int = 30000,
) -> tuple[str, DocumentMetadata, dict[str, str], dict[str, list[str]]]:
    """Crawl đồng thời trang chính, trang thuộc tính, và trang lược đồ của văn bản."""
    thuoc_tinh_url = _make_tab_url(url, "thuoc-tinh")
    luoc_do_url = _make_tab_url(url, "luoc-do")

    # 1.   Khởi tạo Playwright trong chế độ headless
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="vi-VN",
        )

        # 2.   Tải nội dung trang chính (Toàn văn)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        page.close()

        # 3.   Tải nội dung trang Thuộc tính
        properties_html = ""
        try:
            page_prop = context.new_page()
            page_prop.goto(
                thuoc_tinh_url, wait_until="domcontentloaded", timeout=timeout_ms
            )
            page_prop.wait_for_timeout(2000)
            properties_html = page_prop.content()
            page_prop.close()
        except Exception as e:
            logger.error("Lỗi khi tải tab thuộc tính cho %s: %s", doc_id, e)

        # 4.   Tải nội dung trang Lược đồ
        diagram_html = ""
        try:
            page_diag = context.new_page()
            page_diag.goto(
                luoc_do_url, wait_until="domcontentloaded", timeout=timeout_ms
            )
            page_diag.wait_for_timeout(2000)
            diagram_html = page_diag.content()
            page_diag.close()
        except Exception as e:
            logger.error("Lỗi khi tải tab lược đồ cho %s: %s", doc_id, e)

        browser.close()

    # 5.   Trích xuất dữ liệu thô và cấu trúc hóa
    metadata = _extract_metadata(
        body_text, doc_id=doc_id, number=number, source_url=url
    )
    full_text = "\n".join(_extract_body_lines(body_text))

    properties = parse_properties_html(properties_html)
    diagram = parse_diagram_html(diagram_html)

    return full_text, metadata, properties, diagram


def crawl_and_save(
    url: str, doc_id: str, number: str, raw_dir: Path
) -> DocumentMetadata:
    """Crawl + lưu `data/raw/<doc_id>/source.txt` + `metadata.json` + `properties.json` + `diagram.json`."""
    # 1.   Thực hiện crawl tất cả các tab cần thiết
    full_text, metadata, properties, diagram = fetch_document_all_tabs(
        url, doc_id=doc_id, number=number
    )

    # 2.   Tạo thư mục lưu trữ dữ liệu thô nếu chưa tồn tại
    out_dir = raw_dir / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3.   Lưu nội dung toàn văn (source.txt)
    (out_dir / "source.txt").write_text(full_text, encoding="utf-8")

    # 4.   Lưu siêu dữ liệu cơ bản (metadata.json)
    (out_dir / "metadata.json").write_text(
        metadata.model_dump_json(by_alias=True, indent=2, exclude_none=True),
        encoding="utf-8",
    )

    # 5.   Lưu các thuộc tính chi tiết (properties.json)
    (out_dir / "properties.json").write_text(
        json.dumps(properties, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 6.   Lưu lược đồ quan hệ liên kết (diagram.json)
    (out_dir / "diagram.json").write_text(
        json.dumps(diagram, ensure_ascii=False, indent=2),
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
    logger.info(
        "Bắt đầu crawl hàng loạt dựa trên tìm kiếm với từ khóa: '%s', giới hạn: %d",
        query,
        limit,
    )

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
        page.wait_for_selector(
            "div[class*='DocumentCard_documentTitle__']", timeout=timeout_ms
        )
        page.wait_for_timeout(2000)

        # 5.   Lặp qua các trang để thu thập đủ số lượng URL mong muốn
        while len(links_to_crawl) < limit:
            title_locators = page.locator(
                "div[class*='DocumentCard_documentTitle__']"
            ).all()
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
                page.wait_for_selector(
                    "div[class*='DocumentCard_documentTitle__']", timeout=timeout_ms
                )
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
