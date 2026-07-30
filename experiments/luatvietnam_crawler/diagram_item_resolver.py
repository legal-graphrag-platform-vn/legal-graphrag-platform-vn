"""Diagram Item Link Resolver for LuatVietnam experiment.

Tra cứu bổ sung url và number cho các item trong diagram.json từ vbpl.vn bằng cách tìm kiếm Tiêu đề (Chính xác cụm từ trên).
Hỗ trợ:
- Cache tự động (Title -> URL & Number) tránh tìm lại các tiêu đề trùng lặp.
- Checkpoint (diagram_item_checkpoint.json) lưu vết công việc đã làm.
- Lưu trữ danh sách tiêu đề không tìm thấy (vbpl_item_not_found.json).
- Đa luồng (Multithreading) + Chia Batch (50 docs/batch, nghỉ 10s giữa mỗi batch).
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

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Constants
VBPL_BASE_URL = "https://vbpl.vn"
DEFAULT_TIMEOUT_MS = 30000
WAIT_DOM_STABLE_MS = 2500
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
            print(f"\n--- [Hoan thanh Batch {self.batch_count}] Da xu ly {self.docs_in_batch} diagram files. Nghi {self.batch_delay_seconds}s truoc khi sang Batch tiếp theo ---\n")
            time.sleep(self.batch_delay_seconds)
            self.docs_in_batch = 0
            self.batch_count += 1


def resolve_title_on_vbpl(
    page: Any,
    context: Any,
    title: str,
) -> dict[str, str | None] | None:
    """Tra cứu tiêu đề văn bản trên vbpl.vn và bóc tách url cùng number chính thức."""
    try:
        # // 1.   Truy cập https://vbpl.vn/
        for attempt in range(1, 4):
            try:
                page.goto(VBPL_BASE_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                page.wait_for_timeout(1000)
                break
            except Exception as exc:
                if attempt == 3:
                    raise exc
                page.wait_for_timeout(2000)

        # // 2.   Tích Radio 'Tiêu đề' + Checkbox 'Chính xác cụm từ trên'
        radio_title = page.locator("input[type='radio'][value='title']").first
        if radio_title.count() > 0:
            radio_title.check(force=True)
        else:
            page.locator("label:has-text('Tiêu đề') input[type='radio']").first.check(force=True)

        page.locator("label:has-text('Chính xác cụm từ trên') input[type='checkbox']").first.check(force=True)

        # // 3.   Nhập từ khóa tìm kiếm và Enter
        kw_input = page.locator("#keyword").first
        kw_input.fill(title)
        kw_input.press("Enter")
        page.wait_for_timeout(WAIT_DOM_STABLE_MS)

        # // 4.   Kiểm tra kết quả đầu tiên
        title_loc = page.locator("span.block.cursor-pointer, div[class*='documentTitle'], a.ant-typography").first
        if title_loc.count() == 0:
            return None

        # Click mở tab chi tiết mới
        with context.expect_page(timeout=10000) as new_page_info:
            title_loc.click()

        detail_page = new_page_info.value
        detail_page.wait_for_load_state("domcontentloaded")
        result_url = detail_page.url

        # // 5.   Chuyển tab 'Thuộc tính' để lấy Số hiệu chính thức
        detail_page.locator(".ant-tabs-tab:has-text('Thuộc tính')").first.click()
        detail_page.wait_for_timeout(1500)

        soup = BeautifulSoup(detail_page.content(), "lxml")
        prop_pane = soup.select_one("#rc-tabs-0-panel-thuoc-tinh, div[id*='panel-thuoc-tinh'], .ant-tabs-tabpane-active") or soup

        extracted_number: str | None = None
        for container in prop_pane.select(".ant-descriptions-item-container, tr, .property-item"):
            lbl_el = container.select_one(".ant-descriptions-item-label, td:first-child, th:first-child, .label")
            val_el = container.select_one(".ant-descriptions-item-content, td:nth-child(2), .value")
            if lbl_el and val_el:
                lbl = lbl_el.get_text(" ", strip=True).lower().rstrip(":")
                val = val_el.get_text(" ", strip=True)
                if "số hiệu" in lbl:
                    val_strip = val.strip()
                    if val_strip and val_strip not in {"--", "---", "-", "null", "None"}:
                        extracted_number = val_strip
                    break

        detail_page.close()

        return {
            "url": result_url,
            "number": extracted_number,
        }

    except Exception as err:
        logger.error(f"Lỗi khi tra cứu tiêu đề '{title}': {err}")
        return None


def _resolver_worker(
    worker_id: int,
    work_queue: queue.Queue[tuple[int, Path]],
    total_docs: int,
    resolved_cache: dict[str, dict[str, str | None]],
    not_found_set: set[str],
    checkpoint_data: dict[str, Any],
    not_found_list: list[dict[str, Any]],
    lock: threading.Lock(),
    batch_tracker: BatchTracker,
    checkpoint_file: Path,
    not_found_file: Path,
    skip_existing: bool,
    delay_seconds: float,
) -> None:
    """Worker thread xử lý bổ sung diagram.json bằng Playwright context riêng."""
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

            idx, diag_file = item
            doc_id = diag_file.parent.name

            try:
                diag_data = json.loads(diag_file.read_text(encoding="utf-8"))
                groups = diag_data.get("groups", [])
                is_modified = False

                for group in groups:
                    for item_obj in group.get("items", []):
                        item_title = item_obj.get("title")
                        if not item_title or item_title == "--":
                            continue

                        # Đã có đủ url và number -> Bỏ qua
                        if item_obj.get("url") and item_obj.get("number"):
                            continue

                        # Bỏ external_id theo yêu cầu
                        item_obj.pop("external_id", None)

                        # // 1.   Kiểm tra Cache tiêu đề trước
                        cached_result = None
                        with lock:
                            if item_title in resolved_cache:
                                cached_result = resolved_cache[item_title]
                            elif item_title in not_found_set:
                                cached_result = "NOT_FOUND"

                        if cached_result == "NOT_FOUND":
                            continue

                        if cached_result is not None and isinstance(cached_result, dict):
                            if cached_result.get("url"):
                                item_obj["url"] = cached_result["url"]
                            if cached_result.get("number"):
                                item_obj["number"] = cached_result["number"]
                            is_modified = True
                            continue

                        # // 2.   Tra cứu thực tế trên VBPL bằng Tiêu đề
                        safe_title_print = item_title[:50].encode("ascii", "ignore").decode("ascii")
                        print(f"[{idx}/{total_docs}] [Worker {worker_id}] Tra cuu item title: '{safe_title_print}...'")
                        res = resolve_title_on_vbpl(page, context, item_title)

                        with lock:
                            if res and res.get("url"):
                                resolved_cache[item_title] = res
                                item_obj["url"] = res["url"]
                                if res.get("number"):
                                    item_obj["number"] = res["number"]
                                is_modified = True
                                print(f"  [OK] [Worker {worker_id}] Tim thay URL: {res['url']}")
                            else:
                                not_found_set.add(item_title)
                                not_found_list.append({
                                    "doc_id": doc_id,
                                    "title": item_title,
                                    "timestamp": _utc_now_iso(),
                                })
                                not_found_file.write_text(json.dumps(not_found_list, ensure_ascii=False, indent=2), encoding="utf-8")
                                print(f"  -> [Worker {worker_id}] Khong tim thay item: '{safe_title_print}...'")

                        if delay_seconds > 0:
                            time.sleep(delay_seconds)

                # // 3.   Lưu lại diagram.json nếu có cập nhật
                if is_modified:
                    diag_file.write_text(json.dumps(diag_data, ensure_ascii=False, indent=2), encoding="utf-8")

                with lock:
                    checkpoint_data["completed_docs"].append(doc_id)
                    checkpoint_data["processed_count"] = len(checkpoint_data["completed_docs"])
                    checkpoint_data["resolved_cache"] = resolved_cache
                    checkpoint_data["updated_at"] = _utc_now_iso()
                    checkpoint_file.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    batch_tracker.increment_and_check_delay()

            except Exception as exc:
                logger.error(f"Lỗi khi xử lý diagram cho {doc_id}: {exc}")
            finally:
                work_queue.task_done()

        browser.close()


def resolve_diagram_items(
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
    """Thực hiện tra cứu bổ sung url và number cho tất cả item trong diagram.json."""
    # // 1.   Lấy danh sách tất cả file diagram.json hiện có
    diag_files = sorted(
        [p for p in raw_dir.glob("LTV_*/diagram.json") if p.is_file()],
        key=lambda p: p.parent.name,
    )
    if max_documents:
        diag_files = diag_files[:max_documents]

    # Target checkpoint & not_found files
    if checkpoint_file is None:
        checkpoint_file = raw_dir.parent / "diagram_item_checkpoint.json"
    if not_found_file is None:
        not_found_file = raw_dir.parent / "vbpl_item_not_found.json"

    # // 2.   Nạp trạng thái checkpoint & cache nếu có
    checkpoint_data: dict[str, Any] = {
        "updated_at": _utc_now_iso(),
        "processed_count": 0,
        "completed_docs": [],
        "resolved_cache": {},
    }
    if checkpoint_file.exists():
        try:
            checkpoint_data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    completed_docs_set = set(checkpoint_data.get("completed_docs", []))
    resolved_cache: dict[str, dict[str, str | None]] = checkpoint_data.get("resolved_cache", {})

    not_found_list: list[dict[str, Any]] = []
    if not_found_file.exists():
        try:
            not_found_list = json.loads(not_found_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    not_found_set = set(item.get("title") for item in not_found_list if item.get("title"))

    # // 3.   Nạp các file diagram chưa làm vào Queue
    work_queue: queue.Queue[tuple[int, Path]] = queue.Queue()
    total = len(diag_files)
    for idx, df in enumerate(diag_files, 1):
        doc_id = df.parent.name
        if skip_existing and doc_id in completed_docs_set:
            continue
        work_queue.put((idx, df))

    lock = threading.Lock()
    batch_tracker = BatchTracker(batch_size=batch_size, batch_delay_seconds=batch_delay_seconds)
    threads: list[threading.Thread] = []

    print(f"Khoi chay Diagram Item Link Resolver ({concurrency} workers, {batch_size} docs/batch, nghii batch {batch_delay_seconds}s)...")

    # // 4.   Khởi tạo các worker threads
    for i in range(1, concurrency + 1):
        t = threading.Thread(
            target=_resolver_worker,
            args=(
                i,
                work_queue,
                total,
                resolved_cache,
                not_found_set,
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

    # // 5.   Chờ tất cả các luồng hoàn thành
    for t in threads:
        t.join()

    return checkpoint_data
