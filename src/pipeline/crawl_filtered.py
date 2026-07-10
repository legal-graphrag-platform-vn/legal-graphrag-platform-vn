import re
import sys
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from src.crawler.vbpl_crawler import crawl_and_save, _USER_AGENT
from src.config import settings

# Đảm bảo in tiếng Việt không lỗi font trên console Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logger = logging.getLogger("crawl_filtered")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def extract_checked_documents(data_dir: Path) -> list[dict]:
    # Regex tìm số hiệu văn bản (vd: 297/2025/NĐ-CP hoặc 82/2025/TT-BTC)
    number_pattern = re.compile(r"(\d+(?:/\d+)?/[A-ZĐa-z0-9\-]+)")
    
    seen_numbers = set()
    items = []
    
    for file_path in sorted(data_dir.glob("l*_filtered.md")):
        lines = file_path.read_text(encoding="utf-8").splitlines()
        in_checked_section = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## ") and "✅" in stripped:
                in_checked_section = True
                continue
            elif stripped.startswith("## ") and "✅" not in stripped:
                in_checked_section = False
                continue
            elif stripped.startswith("---"):
                in_checked_section = False
                continue
                
            if in_checked_section and stripped.startswith("- "):
                content = stripped[2:].strip()
                
                # Trích xuất số hiệu văn bản
                num_match = number_pattern.search(content)
                if num_match:
                    number = num_match.group(1)
                    if number not in seen_numbers:
                        seen_numbers.add(number)
                        # Xác định loại văn bản từ đầu nội dung dòng
                        title_lower = content.lower()
                        if title_lower.startswith("nghị định"):
                            prefix = "ND"
                        elif title_lower.startswith("thông tư"):
                            prefix = "TT"
                        elif title_lower.startswith("quyết định"):
                            prefix = "QD"
                        elif title_lower.startswith("nghị quyết"):
                            prefix = "NQ"
                        elif title_lower.startswith("luật"):
                            prefix = "L"
                        else:
                            prefix = "DOC"
                        
                        # Sinh doc_id khớp với crawl_by_search
                        parts = number.split("/")
                        num_part = parts[0]
                        year_part = parts[1] if len(parts) > 1 else "unknown"
                        doc_id = f"{prefix}{num_part}_{year_part}"
                        
                        items.append({
                            "doc_id": doc_id,
                            "number": number,
                            "original_title": content,
                            "source_file": file_path.name
                        })
                else:
                    logger.warning(f"Bỏ qua dòng không có số hiệu trong {file_path.name}: '{content}'")
                    
    return items

def search_and_crawl_document(item: dict, raw_dir: Path, timeout_ms: int = 30000) -> bool:
    doc_id = item["doc_id"]
    number = item["number"]
    
    # Kiểm tra xem tài liệu đã được crawl chưa
    out_dir = raw_dir / doc_id
    if (out_dir / "source.txt").exists() and (out_dir / "metadata.json").exists():
        logger.info(f"Tài liệu {doc_id} ({number}) đã tồn tại. Bỏ qua.")
        return True

    # Xác định loại văn bản đầy đủ từ doc_id prefix
    if doc_id.startswith("ND"):
        full_name = "Nghị định"
    elif doc_id.startswith("TT"):
        full_name = "Thông tư"
    elif doc_id.startswith("QD"):
        full_name = "Quyết định"
    elif doc_id.startswith("NQ"):
        full_name = "Nghị quyết"
    elif doc_id.startswith("L"):
        full_name = "Luật"
    else:
        full_name = ""

    # Tập hợp các phương án tìm kiếm (từ hẹp đến rộng)
    search_strategies = []
    if full_name:
        search_strategies.append({"query": f"{full_name} số {number}", "search_in": "title", "exact": True})
        search_strategies.append({"query": f"{full_name} {number}", "search_in": "title", "exact": True})
    search_strategies.append({"query": number, "search_in": "title", "exact": True})
    search_strategies.append({"query": number, "search_in": "number", "exact": True})

    detail_url = None
    target_title = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="vi-VN",
        )
        page = context.new_page()

        for strategy in search_strategies:
            query_str = strategy["query"]
            search_in = strategy["search_in"]
            exact = strategy["exact"]

            logger.info(f"Thử tìm kiếm với: '{query_str}' | Trong: {search_in} | Khớp chính xác: {exact}")

            try:
                url = "https://vbpl.vn/van-ban/trung-uong"
                # Dùng domcontentloaded để tải nhanh hơn, tránh timeout do các tracker bên thứ ba tải chậm
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)

                # Điền từ khóa
                page.fill("input#keyword", query_str)
                page.wait_for_timeout(500)

                # Ẩn gợi ý tự động
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

                # Cấu hình tìm kiếm trong Tiêu đề hoặc Số hiệu
                if search_in == "title":
                    page.click("input[type='radio'][value='title']")
                elif search_in == "number":
                    page.click("label:has-text('Số hiệu')")
                page.wait_for_timeout(500)

                # Cấu hình khớp chính xác cụm từ
                if exact:
                    page.click("label:has-text('Chính xác cụm từ trên')")
                page.wait_for_timeout(500)

                # Nhấn nút tìm kiếm (Sử dụng nút .first đại diện cho ô tìm kiếm chính)
                search_btn = page.locator("button:has-text('Tìm kiếm')").first
                search_btn.click(force=True)
                page.wait_for_timeout(2000)

                # Chờ danh sách kết quả hiển thị
                page.wait_for_selector("div[class*='DocumentCard_documentTitle__']", timeout=10000)
                page.wait_for_timeout(1000)

                # Kiểm tra xem có chứa thông báo "Không tìm thấy" trong body không
                body_text = page.inner_text("body")
                if "Không tìm thấy" in body_text:
                    logger.warning(f"Không tìm thấy kết quả cho chiến lược này.")
                    continue

                # Lấy danh sách kết quả
                title_locators = page.locator("div[class*='DocumentCard_documentTitle__']").all()
                if not title_locators:
                    continue

                # Lọc kết quả chứa đúng số hiệu cần tìm
                found_locator = None
                for locator in title_locators:
                    title_text = locator.inner_text().strip()
                    if number.lower() in title_text.lower():
                        found_locator = locator
                        target_title = title_text
                        break

                if found_locator:
                    logger.info(f"Tìm thấy tiêu đề khớp: '{target_title}'")
                    # Click mở tab chi tiết mới
                    with context.expect_page() as new_page_info:
                        found_locator.click()
                    new_page = new_page_info.value
                    new_page.wait_for_timeout(1500)
                    detail_url = new_page.url
                    new_page.close()
                    break # Tìm thấy thành công, thoát khỏi vòng lặp strategies
                else:
                    logger.warning("Không tìm thấy dòng kết quả nào chứa đúng số hiệu trong tiêu đề.")

            except Exception as e:
                logger.warning(f"Lỗi khi thực hiện chiến lược tìm kiếm '{query_str}': {e}")
                continue

        browser.close()

    if not detail_url:
        logger.error(f"Thất bại hoàn toàn khi tìm kiếm số hiệu {number} với tất cả các chiến lược.")
        return False

    # Chạy crawl và lưu dữ liệu bằng hàm có sẵn
    try:
        crawl_and_save(detail_url, doc_id, number, raw_dir)
        logger.info(f"Crawl thành công {doc_id} từ {detail_url}")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi crawl lưu tài liệu {doc_id}: {e}")
        return False

def main():
    data_dir = Path("docs/data")
    raw_dir = settings.data_raw_dir
    
    # 1. Trích xuất danh sách các tài liệu cần crawl từ file filter
    items = extract_checked_documents(data_dir)
    logger.info(f"Tổng cộng có {len(items)} tài liệu độc nhất cần crawl.")
    
    # 2. Thực hiện crawl tuần tự từng tài liệu
    success_count = 0
    fail_count = 0
    
    for idx, item in enumerate(items, 1):
        logger.info(f"--- [{idx}/{len(items)}] ---")
        success = search_and_crawl_document(item, raw_dir)
        if success:
            success_count += 1
        else:
            fail_count += 1
            
    logger.info(f"Hoàn thành! Thành công: {success_count}, Thất bại: {fail_count}")

if __name__ == "__main__":
    main()
