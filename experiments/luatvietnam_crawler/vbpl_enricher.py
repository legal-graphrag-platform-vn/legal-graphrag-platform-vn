"""VBPL Enricher for LuatVietnam experiment with Multithreading & Batching.

Tra cứu số hiệu văn bản trên vbpl.vn/van-ban/trung-uong, bóc tách thuộc tính (properties.json)
và lược đồ (diagram.json) chuẩn hóa theo spec `supplemental_crawl_artifacts.md`.
Hỗ trợ đa luồng (multithreading) + chia batch (50 văn bản/batch, nghỉ 10s giữa mỗi batch).
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Constants
VBPL_TRUNG_UONG_URL = "https://vbpl.vn/van-ban/trung-uong"
VBPL_BASE_URL = "https://vbpl.vn"
DEFAULT_TIMEOUT_MS = 30000
WAIT_DOM_STABLE_MS = 2000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DIAGRAM_SCHEMA_VERSION = "luatvietnam-diagram-v1"

# Mapping nhãn VBPL sang JSON field của properties.json theo đúng spec 11 field
LABEL_TO_PROPERTY_KEY = {
    "số hiệu": "number",
    "số hiệu văn bản": "number",
    "loại văn bản": "document_type",
    "loại vb": "document_type",
    "ngành": "sector",
    "ngày ban hành": "issued_date",
    "lĩnh vực": "field",
    "lĩnh vực hoạt động": "field",
    "ngày có hiệu lực": "effective_date",
    "ngày hiệu lực": "effective_date",
    "tình trạng hiệu lực": "status",
    "trạng thái hiệu lực": "status",
    "trạng thái": "status",
    "ngày hết hiệu lực": "expiry_date",
    "cơ quan ban hành": "issuing_authority",
    "cơ quan ban hành/ chức danh": "issuing_authority",
    "chức danh": "signer_title",
    "chức danh người ký": "signer_title",
    "người ký": "signer_name",
}

EXACT_11_PROPERTY_FIELDS = (
    "number",
    "document_type",
    "sector",
    "issued_date",
    "field",
    "effective_date",
    "status",
    "expiry_date",
    "issuing_authority",
    "signer_title",
    "signer_name",
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_value(val: str | None) -> str | None:
    if not val:
        return None
    val_strip = val.strip()
    if not val_strip or val_strip in {"--", "---", "-", "null", "None"}:
        return None
    return val_strip


def parse_properties_tab(html: str, default_number: str) -> dict[str, str | None]:
    """Parse HTML tab Thuộc tính theo đúng spec 11 fields của supplemental_crawl_artifacts.md."""
    # // 1.   Khởi tạo dictionary đủ 11 field bằng None
    result: dict[str, str | None] = {field: None for field in EXACT_11_PROPERTY_FIELDS}
    result["number"] = _clean_value(default_number)

    # // 2.   Parse các dòng bảng thuộc tính AntD trong HTML
    soup = BeautifulSoup(html, "lxml")
    prop_pane = soup.select_one("#rc-tabs-0-panel-thuoc-tinh, div[id*='panel-thuoc-tinh'], .ant-tabs-tabpane-active") or soup

    for container in prop_pane.select(".ant-descriptions-item-container, tr, .property-item"):
        lbl_el = container.select_one(".ant-descriptions-item-label, td:first-child, th:first-child, .label")
        val_el = container.select_one(".ant-descriptions-item-content, td:nth-child(2), .value")
        if lbl_el and val_el:
            label_text = lbl_el.get_text(" ", strip=True).lower().rstrip(":")
            val_text = val_el.get_text(" ", strip=True)

            key = LABEL_TO_PROPERTY_KEY.get(label_text)
            if key and key in result:
                result[key] = _clean_value(val_text)

    return result


def parse_diagram_tab(
    html: str,
    external_id: str,
    source_url: str,
) -> dict[str, Any]:
    """Parse HTML tab Lược đồ theo đúng spec luatvietnam-diagram-v1."""
    soup = BeautifulSoup(html, "lxml")
    diag_pane = soup.select_one("#rc-tabs-0-panel-luoc-do, div[id*='panel-luoc-do'], .ant-tabs-tabpane-active") or soup
    groups: list[dict[str, Any]] = []

    # // 1.   Duyệt qua từng thẻ card nhóm quan hệ (ant-card)
    for card in diag_pane.select(".ant-card, .luocdo-group, .diagram-group"):
        title_el = card.select_one("span.font-bold, .title, h3, h4, .group-title")
        if not title_el:
            continue
        raw_header = title_el.get_text(" ", strip=True)
        if not raw_header or raw_header == "Lược đồ":
            continue

        count_match = re.search(r"\((\d+)\)", raw_header)
        label = re.sub(r"\s*\(\d+\)\s*$", "", raw_header).strip()
        declared_count = int(count_match.group(1)) if count_match else 0

        items: list[dict[str, Any]] = []
        for li in card.select("ul > li, .item"):
            a = li.select_one("a[href]")
            if not a:
                rel_title = li.get_text(" ", strip=True)
                if rel_title == "--" or not rel_title:
                    continue
                num_m = re.search(r"\b\d{1,4}(?:/\d{4})?/[A-ZĐƠƯ0-9-]+(?:/[A-ZĐƠƯ0-9-]+)*\b", rel_title)
                items.append({
                    "title": rel_title,
                    "number": num_m.group(0) if num_m else None,
                    "url": None,
                    "external_id": None,
                })
            else:
                rel_title = a.get_text(" ", strip=True)
                rel_url = urljoin(VBPL_BASE_URL, str(a["href"])) if a.get("href") else None
                num_m = re.search(r"\b\d{1,4}(?:/\d{4})?/[A-ZĐƠƯ0-9-]+(?:/[A-ZĐƠƯ0-9-]+)*\b", rel_title)
                ext_m = re.search(r"-([a-f0-9-]+)$", rel_url or "", re.IGNORECASE)
                items.append({
                    "title": rel_title,
                    "number": num_m.group(0) if num_m else None,
                    "url": rel_url,
                    "external_id": ext_m.group(1) if ext_m else None,
                })

        groups.append({
            "label": label,
            "declared_count": declared_count,
            "items": items,
        })

    # // 2.   Trả về đối tượng JSON diagram theo đúng spec
    return {
        "schema_version": DIAGRAM_SCHEMA_VERSION,
        "external_id": external_id,
        "source_url": source_url,
        "fetched_at": _utc_now_iso(),
        "groups": groups,
    }


class BatchTracker:
    def __init__(self, batch_size: int, batch_delay_seconds: float) -> None:
        self.batch_size = batch_size
        self.batch_delay_seconds = batch_delay_seconds
        self.docs_in_batch = 0
        self.batch_count = 1

    def increment_and_check_delay(self) -> None:
        if self.batch_size <= 0 or self.batch_delay_seconds <= 0:
            return
        self.docs_in_batch += 1
        if self.docs_in_batch >= self.batch_size:
            print(f"\n--- [Hoàn thành Batch {self.batch_count}] Đã cào {self.docs_in_batch} văn bản. Nghỉ {self.batch_delay_seconds} giây trước khi chuyển sang Batch {self.batch_count + 1} ---\n")
            time.sleep(self.batch_delay_seconds)
            self.docs_in_batch = 0
            self.batch_count += 1


def _worker_thread_func(
    worker_id: int,
    work_queue: queue.Queue[tuple[int, Path]],
    total_docs: int,
    completed_set: set[str],
    checkpoint_data: dict[str, Any],
    not_found_list: list[dict[str, Any]],
    lock: threading.Lock(),
    batch_tracker: BatchTracker,
    checkpoint_file: Path,
    not_found_file: Path,
    skip_existing: bool,
    delay_seconds: float,
) -> None:
    """Worker thread xử lý cào văn bản bằng một Playwright Browser Context riêng."""
    # // 1.   Khởi tạo Playwright Session riêng cho worker thread này
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
        )
        page = context.new_page()

        while True:
            try:
                item = work_queue.get_nowait()
            except queue.Empty:
                break

            idx, folder = item
            doc_id = folder.name
            meta_file = folder / "metadata.json"
            prop_file = folder / "properties.json"
            diag_file = folder / "diagram.json"

            # Skip check
            with lock:
                is_already_done = doc_id in completed_set or (skip_existing and prop_file.exists() and diag_file.exists())
                if is_already_done:
                    checkpoint_data["skipped_count"] = checkpoint_data.get("skipped_count", 0) + 1
                    work_queue.task_done()
                    continue

            if not meta_file.exists():
                work_queue.task_done()
                continue

            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                number = meta.get("number")
                ext_id = meta.get("external_id") or doc_id.replace("LTV_", "")

                if not number or number in {"None", "null"}:
                    print(f"[{idx}/{total_docs}] [Worker {worker_id}] Bỏ qua {doc_id} vì không có số hiệu hợp lệ.")
                    with lock:
                        checkpoint_data["skipped_count"] = checkpoint_data.get("skipped_count", 0) + 1
                    work_queue.task_done()
                    continue

                print(f"[{idx}/{total_docs}] [Worker {worker_id}] Tìm kiếm VBPL cho {doc_id} ({number})...")

                # // 2.   Truy cập https://vbpl.vn/van-ban/trung-uong và tìm kiếm số hiệu
                for attempt in range(1, 4):
                    try:
                        page.goto(VBPL_TRUNG_UONG_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                        page.wait_for_timeout(1000)
                        break
                    except Exception as goto_err:
                        if attempt == 3:
                            raise goto_err
                        page.wait_for_timeout(2000)

                page.locator("input[type='radio'][value='number']").check(force=True)
                page.locator("label:has-text('Chính xác cụm từ trên') input[type='checkbox']").check(force=True)

                kw_input = page.locator("#keyword").first
                kw_input.fill(number)
                kw_input.press("Enter")
                page.wait_for_timeout(WAIT_DOM_STABLE_MS)

                # // 3.   Mở kết quả đầu tiên vào tab mới
                title_loc = page.locator("span.block.cursor-pointer, div[class*='documentTitle']").first
                if title_loc.count() == 0:
                    print(f"  -> [Worker {worker_id}] Không tìm thấy số hiệu {number} trên VBPL. Đã ghi nhận not_found.")
                    with lock:
                        checkpoint_data["not_found_count"] = checkpoint_data.get("not_found_count", 0) + 1
                        not_found_list.append({
                            "doc_id": doc_id,
                            "number": number,
                            "title": meta.get("title"),
                            "timestamp": _utc_now_iso(),
                        })
                        not_found_file.write_text(json.dumps(not_found_list, ensure_ascii=False, indent=2), encoding="utf-8")
                        batch_tracker.increment_and_check_delay()
                else:
                    with context.expect_page(timeout=10000) as new_page_info:
                        title_loc.click()

                    detail_page = new_page_info.value
                    detail_page.wait_for_load_state("domcontentloaded")

                    # // 4.   Chuyển tab 'Thuộc tính' để trích xuất properties.json
                    detail_page.locator(".ant-tabs-tab:has-text('Thuộc tính')").first.click()
                    detail_page.wait_for_timeout(1500)
                    properties = parse_properties_tab(detail_page.content(), default_number=number)

                    # // 5.   Chuyển tab 'Lược đồ' để trích xuất diagram.json
                    detail_page.locator(".ant-tabs-tab:has-text('Lược đồ')").first.click()
                    detail_page.wait_for_timeout(1500)
                    diagram = parse_diagram_tab(detail_page.content(), external_id=ext_id, source_url=detail_page.url)

                    detail_page.close()

                    # // 6.   Ghi file JSON vào thư mục LTV_<id>/
                    prop_file.write_text(json.dumps(properties, ensure_ascii=False, indent=2), encoding="utf-8")
                    diag_file.write_text(json.dumps(diagram, ensure_ascii=False, indent=2), encoding="utf-8")

                    with lock:
                        completed_set.add(doc_id)
                        checkpoint_data["processed_count"] = checkpoint_data.get("processed_count", 0) + 1
                        checkpoint_data["success_count"] = checkpoint_data.get("success_count", 0) + 1
                        checkpoint_data["completed_ids"] = list(completed_set)
                        checkpoint_data["updated_at"] = _utc_now_iso()
                        checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
                        batch_tracker.increment_and_check_delay()

                    print(f"  ✓ [Worker {worker_id}] Đã lưu properties.json & diagram.json cho {doc_id}")

                if delay_seconds > 0:
                    time.sleep(delay_seconds)

            except Exception as exc:
                logger.error(f"Lỗi [Worker {worker_id}] khi cào VBPL cho {doc_id}: {exc}")
            finally:
                work_queue.task_done()

        browser.close()


def enrich_documents(
    raw_dir: Path,
    *,
    skip_existing: bool = True,
    max_documents: int | None = None,
    checkpoint_file: Path | None = None,
    not_found_file: Path | None = None,
    delay_seconds: float = 0.0,
    concurrency: int = 4,
    batch_size: int = 50,
    batch_delay_seconds: float = 10.0,
) -> dict[str, Any]:
    """Thực hiện enrich cào thuộc tính & lược đồ từ VBPL bằng Đa luồng (Multithreading) và Batch delay."""
    # // 1.   Lấy danh sách các thư mục văn bản LTV_*
    doc_folders = sorted(
        [p for p in raw_dir.glob("LTV_*") if p.is_dir()],
        key=lambda p: p.name,
    )
    if max_documents:
        doc_folders = doc_folders[:max_documents]

    # Target checkpoint & not_found files
    if checkpoint_file is None:
        checkpoint_file = raw_dir.parent / "enrich_checkpoint.json"
    if not_found_file is None:
        not_found_file = raw_dir.parent / "vbpl_not_found.json"

    # // 2.   Nạp trạng thái checkpoint nếu có
    checkpoint_data: dict[str, Any] = {
        "updated_at": _utc_now_iso(),
        "processed_count": 0,
        "success_count": 0,
        "skipped_count": 0,
        "not_found_count": 0,
        "completed_ids": [],
    }
    if checkpoint_file.exists():
        try:
            checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    completed_set = set(checkpoint_data.get("completed_ids", []))
    not_found_list: list[dict[str, Any]] = []
    if not_found_file.exists():
        try:
            not_found_list = json.loads(not_found_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # // 3.   Nạp danh sách công việc vào Queue
    work_queue: queue.Queue[tuple[int, Path]] = queue.Queue()
    total = len(doc_folders)
    for idx, folder in enumerate(doc_folders, 1):
        work_queue.put((idx, folder))

    lock = threading.Lock()
    batch_tracker = BatchTracker(batch_size=batch_size, batch_delay_seconds=batch_delay_seconds)
    threads: list[threading.Thread] = []

    print(f"🚀 Bắt đầu tiến trình cào đa luồng ({concurrency} workers, {batch_size} văn bản/batch, nghỉ batch {batch_delay_seconds}s)...")

    # // 4.   Khởi tạo các worker threads
    for i in range(1, concurrency + 1):
        t = threading.Thread(
            target=_worker_thread_func,
            args=(
                i,
                work_queue,
                total,
                completed_set,
                checkpoint_data,
                not_found_list,
                lock,
                batch_tracker,
                checkpoint_file,
                not_found_file,
                skip_existing,
                delay_seconds,
            ),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # // 5.   Chờ tất cả các luồng hoàn thành công việc
    for t in threads:
        t.join()

    return checkpoint_data
