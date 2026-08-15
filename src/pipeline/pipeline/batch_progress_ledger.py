"""Batch Progress Ledger — Theo dõi trạng thái tiến độ xử lý hàng loạt của pipeline.

Lưu trữ trạng thái thành công, thất bại, hoặc đang chờ cho từng văn bản theo đợt
tại data/processed/batch_progress.json. Hỗ trợ cơ chế Resume và Retry lỗi.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.pipeline.config import settings

logger = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = settings.data_processed_dir / "batch_progress.json"
_LEDGER_LOCK = threading.Lock()


def load_ledger(ledger_path: Path = DEFAULT_LEDGER_PATH) -> dict[str, dict[str, Any]]:
    """Đọc file ledger ghi nhận tiến độ batch từ ổ đĩa."""
    if not ledger_path.exists():
        return {}

    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Lỗi đọc batch progress ledger từ {ledger_path}: {exc}")
        return {}


import os
import time

def save_ledger(ledger: dict[str, dict[str, Any]], ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
    """Ghi dữ liệu tiến độ batch ra đĩa an toàn bằng atomic write."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = ledger_path.parent / f"{ledger_path.stem}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)
        temp_path.replace(ledger_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def record_doc_status(
    raw_doc_code: str,
    step: str,
    status: str,
    *,
    error: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """Ghi nhận hoặc cập nhật trạng thái của 1 văn bản tại 1 bước cụ thể với thread lock."""
    with _LEDGER_LOCK:
        ledger = load_ledger(ledger_path)

        if raw_doc_code not in ledger:
            ledger[raw_doc_code] = {
                "status": "PENDING",
                "last_step": "none",
                "history": {},
            }

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
