"""Batch Progress Ledger — Theo dõi trạng thái tiến độ xử lý hàng loạt của pipeline.

Lưu trữ trạng thái thành công, thất bại, hoặc đang chờ cho từng văn bản theo đợt
tại data/processed/batch_progress.json. Hỗ trợ cơ chế Resume và Retry lỗi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.pipeline.config import settings

logger = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = settings.data_processed_dir / "batch_progress.json"


def load_ledger(ledger_path: Path = DEFAULT_LEDGER_PATH) -> dict[str, dict[str, Any]]:
    """Đọc file ledger ghi nhận tiến độ batch từ ổ đĩa."""
    # 1. Trả về dict rỗng nếu file chưa tồn tại
    if not ledger_path.exists():
        return {}

    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Lỗi đọc batch progress ledger từ {ledger_path}: {exc}")
        return {}


def save_ledger(ledger: dict[str, dict[str, Any]], ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
    """Ghi dữ liệu tiến độ batch ra đĩa."""
    # 1. Đảm bảo thư mục cha tồn tại
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Ghi dữ liệu dạng JSON đẹp mắt
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)


def record_doc_status(
    raw_doc_code: str,
    step: str,
    status: str,
    *,
    error: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """Ghi nhận hoặc cập nhật trạng thái của 1 văn bản tại 1 bước cụ thể."""
    # 1. Đọc ledger hiện tại
    ledger = load_ledger(ledger_path)

    # 2. Khởi tạo bản ghi nếu chưa có
    if raw_doc_code not in ledger:
        ledger[raw_doc_code] = {
            "status": "PENDING",
            "last_step": "none",
            "history": {},
        }

    # 3. Cập nhật trạng thái bước hiện tại
    now_iso = datetime.now(timezone.utc).isoformat()
    doc_entry = ledger[raw_doc_code]
    doc_entry["status"] = status
    doc_entry["last_step"] = step
    doc_entry["updated_at"] = now_iso

    if "history" not in doc_entry:
        doc_entry["history"] = {}

    doc_entry["history"][step] = {
        "status": status,
        "updated_at": now_iso,
        "error": error,
    }

    # 4. Ghi ngược lại ổ đĩa
    save_ledger(ledger, ledger_path)


def filter_documents_for_step(
    doc_codes: list[str],
    step: str,
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    retry_failed: bool = False,
) -> list[str]:
    """Lọc danh sách các văn bản cần xử lý cho một bước cụ thể (hỗ trợ Resume/Skip văn bản đã xong)."""
    # 1. Đọc ledger hiện tại
    ledger = load_ledger(ledger_path)
    pending_codes: list[str] = []

    # 2. Kiểm tra từng văn bản
    for code in doc_codes:
        entry = ledger.get(code, {})
        history = entry.get("history", {})
        step_status = history.get(step, {}).get("status")

        # Đã hoàn thành bước này thành công -> Skip
        if step_status == "SUCCESS" and not retry_failed:
            continue

        # Thất bại ở bước này nhưng không bật retry_failed -> Skip
        if step_status == "FAILED" and not retry_failed:
            continue

        pending_codes.append(code)

    return pending_codes
